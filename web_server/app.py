# app.py
import os
import json
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, send_file, session, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import paho.mqtt.client as mqtt
from sqlalchemy import create_engine
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///classguard.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Database setup
db = SQLAlchemy(app)

# Login manager setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# MQTT Configuration
MQTT_BROKER = os.environ.get('MQTT_BROKER', 'broker.hivemq.com')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 1883))
MQTT_TOPIC_SENSORS = "classguard/sensors"
MQTT_TOPIC_CONTROL = "classguard/control"

# Global variables for sensor data
latest_sensor_data = {}
device_status = {'fan': False, 'light': False, 'buzzer': False}

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='viewer')  # 'admin' or 'viewer'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class SensorData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(50))
    temperature = db.Column(db.Float)
    humidity = db.Column(db.Float)
    co2 = db.Column(db.Float)
    light = db.Column(db.Float)
    noise = db.Column(db.Float)
    aqi = db.Column(db.Float)
    class_score = db.Column(db.Integer)
    status = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# MQTT Client Setup
mqtt_client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT Broker!")
        client.subscribe(MQTT_TOPIC_SENSORS)
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        
        # Update global variable
        global latest_sensor_data
        latest_sensor_data = data
        latest_sensor_data['received_at'] = datetime.now().isoformat()
        
        # Save to database
        sensor_data = SensorData(
            device_id=data.get('device_id', 'unknown'),
            temperature=data.get('temperature'),
            humidity=data.get('humidity'),
            co2=data.get('co2'),
            light=data.get('light'),
            noise=data.get('noise'),
            aqi=data.get('aqi'),
            class_score=data.get('class_score', 0),
            status=data.get('status', 'Unknown'),
            timestamp=datetime.fromisoformat(data.get('timestamp', datetime.utcnow().isoformat()))
        )
        db.session.add(sensor_data)
        db.session.commit()
        
    except Exception as e:
        print(f"Error processing MQTT message: {e}")

def start_mqtt_client():
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()

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
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Get latest data
    latest = SensorData.query.order_by(SensorData.timestamp.desc()).first()
    
    # Get hourly averages for charts
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    hourly_data = SensorData.query.filter(SensorData.timestamp >= one_hour_ago).all()
    
    # Prepare chart data
    chart_data = {
        'timestamps': [d.timestamp.strftime('%H:%M') for d in hourly_data[-12:]],  # Last 12 points
        'temperature': [d.temperature for d in hourly_data[-12:] if d.temperature],
        'co2': [d.co2 for d in hourly_data[-12:] if d.co2],
        'light': [d.light for d in hourly_data[-12:] if d.light],
        'noise': [d.noise for d in hourly_data[-12:] if d.noise]
    }
    
    return render_template('dashboard.html', 
                         latest=latest, 
                         device_status=device_status,
                         chart_data=json.dumps(chart_data),
                         user=current_user)

@app.route('/api/sensor_data')
@login_required
def api_sensor_data():
    return jsonify(latest_sensor_data)

@app.route('/api/control', methods=['POST'])
@login_required
def api_control():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json
    device = data.get('device')
    state = data.get('state')
    
    if device in ['fan', 'light', 'buzzer']:
        device_status[device] = state
        
        # Send control command via MQTT
        control_msg = json.dumps({device: state})
        mqtt_client.publish(MQTT_TOPIC_CONTROL, control_msg)
        
        return jsonify({'success': True, device: state})
    
    return jsonify({'error': 'Invalid device'}), 400

@app.route('/history')
@login_required
def history():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    # Filter by date if provided
    date_filter = request.args.get('date')
    query = SensorData.query
    
    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            query = query.filter(db.func.date(SensorData.timestamp) == filter_date)
        except ValueError:
            pass
    
    data = query.order_by(SensorData.timestamp.desc()).paginate(page=page, per_page=per_page)
    
    return render_template('history.html', data=data, current_date=date_filter)

@app.route('/export/pdf')
@login_required
def export_pdf():
    # Get data for the last 24 hours
    one_day_ago = datetime.utcnow() - timedelta(days=1)
    data = SensorData.query.filter(SensorData.timestamp >= one_day_ago).all()
    
    # Create PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    elements.append(Paragraph("CLASSGUARD - Sensor Data Report", styles['Title']))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    
    # Create table data
    table_data = [['Time', 'Temp (°C)', 'Humidity (%)', 'CO2 (ppm)', 'Light (lux)', 'Noise (dB)', 'Score']]
    
    for entry in data[:50]:  # Limit to 50 entries
        table_data.append([
            entry.timestamp.strftime('%H:%M'),
            f"{entry.temperature:.1f}" if entry.temperature else 'N/A',
            f"{entry.humidity:.1f}" if entry.humidity else 'N/A',
            f"{entry.co2:.0f}" if entry.co2 else 'N/A',
            f"{entry.light:.0f}" if entry.light else 'N/A',
            f"{entry.noise:.1f}" if entry.noise else 'N/A',
            str(entry.class_score) if entry.class_score else 'N/A'
        ])
    
    # Create table
    table = Table(table_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(table)
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(buffer, 
                     as_attachment=True, 
                     download_name=f"classguard_report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                     mimetype='application/pdf')

@app.route('/admin/users')
@login_required
def admin_users():
    if current_user.role != 'admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/create_admin')
def create_admin():
    # Only for initial setup - remove this route in production!
    if not User.query.first():
        admin = User(username='admin', email='admin@classguard.com', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        
        viewer = User(username='viewer', email='viewer@classguard.com', role='viewer')
        viewer.set_password('viewer123')
        db.session.add(viewer)
        
        db.session.commit()
        return 'Admin and viewer users created!'
    return 'Users already exist'

# Initialize database and start MQTT
with app.app_context():
    db.create_all()
    start_mqtt_client()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)