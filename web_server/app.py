# app.py - Optimized for Render.com
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import paho.mqtt.client as mqtt
from io import BytesIO
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
if __name__ != '__main__':
    from models import db, User, SensorData
else:
    from .models import db, User, SensorData
    
# Initialize Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///classguard.db').replace('postgres://', 'postgresql://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Database
db = SQLAlchemy(app)

# Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# MQTT Configuration
MQTT_BROKER = os.environ.get('MQTT_BROKER', 'broker.hivemq.com')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 1883))
MQTT_TOPIC_SENSORS = "classguard/sensors"
MQTT_TOPIC_CONTROL = "classguard/control"

# Global variables
latest_data = {}
device_status = {'fan': False, 'light': False, 'buzzer': False}

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='viewer')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class SensorData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    temperature = db.Column(db.Float)
    humidity = db.Column(db.Float)
    co2 = db.Column(db.Float)
    light = db.Column(db.Float)
    noise = db.Column(db.Float)
    score = db.Column(db.Integer)
    status = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Initialize MQTT (non-blocking)
def init_mqtt():
    client = mqtt.Client()
    
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("✓ MQTT Connected")
            client.subscribe(MQTT_TOPIC_SENSORS)
        else:
            print(f"✗ MQTT Connection failed: {rc}")
    
    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            global latest_data
            latest_data = data
            latest_data['received_at'] = datetime.now().isoformat()
            
            # Save to database
            sensor = SensorData(
                temperature=data.get('temperature'),
                humidity=data.get('humidity'),
                co2=data.get('co2'),
                light=data.get('light'),
                noise=data.get('noise'),
                score=data.get('class_score', 0),
                status=data.get('status', 'Unknown')
            )
            db.session.add(sensor)
            db.session.commit()
            
        except Exception as e:
            print(f"MQTT Error: {e}")
    
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        return client
    except:
        print("MQTT broker not available, continuing without MQTT")
        return None

# Initialize MQTT client
mqtt_client = init_mqtt()

# Routes
@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    latest = SensorData.query.order_by(SensorData.timestamp.desc()).first()
    
    # Get chart data (last 1 hour)
    hour_ago = datetime.utcnow() - timedelta(hours=1)
    records = SensorData.query.filter(SensorData.timestamp >= hour_ago).order_by(SensorData.timestamp).all()
    
    chart_data = {
        'times': [r.timestamp.strftime('%H:%M') for r in records[-12:]],
        'temp': [r.temperature for r in records[-12:] if r.temperature],
        'co2': [r.co2 for r in records[-12:] if r.co2],
        'light': [r.light for r in records[-12:] if r.light],
        'noise': [r.noise for r in records[-12:] if r.noise]
    }
    
    return render_template('dashboard.html', 
                         latest=latest, 
                         status=device_status,
                         chart_data=json.dumps(chart_data),
                         user=current_user)

@app.route('/api/data')
@login_required
def api_data():
    return jsonify(latest_data)

@app.route('/api/control', methods=['POST'])
@login_required
def api_control():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json
    device = data.get('device')
    state = data.get('state')
    
    if device in device_status:
        device_status[device] = state
        if mqtt_client:
            mqtt_client.publish(MQTT_TOPIC_CONTROL, json.dumps({device: state}))
        return jsonify({'success': True})
    
    return jsonify({'error': 'Invalid device'}), 400

@app.route('/history')
@login_required
def history():
    page = request.args.get('page', 1, type=int)
    data = SensorData.query.order_by(SensorData.timestamp.desc()).paginate(page=page, per_page=20)
    return render_template('history.html', data=data)

@app.route('/export/pdf')
@login_required
def export_pdf():
    # Simple PDF export
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    elements.append(Paragraph("CLASSGUARD Report", styles['Title']))
    
    # Add table
    data = [['Time', 'Temp', 'Humidity', 'CO2', 'Score']]
    records = SensorData.query.order_by(SensorData.timestamp.desc()).limit(20).all()
    
    for r in records:
        data.append([
            r.timestamp.strftime('%H:%M'),
            f"{r.temperature:.1f}" if r.temperature else 'N/A',
            f"{r.humidity:.1f}" if r.humidity else 'N/A',
            f"{r.co2:.0f}" if r.co2 else 'N/A',
            str(r.score) if r.score else 'N/A'
        ])
    
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(buffer, mimetype='application/pdf',
                     download_name=f'report_{datetime.now().strftime("%Y%m%d")}.pdf')

@app.route('/init')
def init_db():
    # Create default users
    if not User.query.first():
        admin = User(username='admin', role='admin')
        admin.set_password('admin123')
        
        viewer = User(username='viewer', role='viewer')
        viewer.set_password('viewer123')
        
        db.session.add(admin)
        db.session.add(viewer)
        db.session.commit()
        
        return 'Database initialized with admin/viewer users'
    return 'Database already initialized'

# Create database tables
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
