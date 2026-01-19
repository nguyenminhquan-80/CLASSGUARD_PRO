from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Không cần GUI
from datetime import datetime
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import requests
import json
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-this'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///classguard.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ================== MÔ HÌNH DỮ LIỆU ==================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='viewer')  # 'admin' hoặc 'viewer'

class SensorData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    temperature = db.Column(db.Float)
    humidity = db.Column(db.Float)
    light = db.Column(db.Float)
    air_quality = db.Column(db.Float)
    sound_level = db.Column(db.Float)
    evaluation = db.Column(db.String(50))
    device_ip = db.Column(db.String(50))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ================== TRANG ĐĂNG NHẬP ==================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.password == password:
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Sai tên đăng nhập hoặc mật khẩu')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ================== TRANG CHỦ ==================
@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)

# ================== API LẤY DỮ LIỆU ==================
@app.route('/api/data')
@login_required
def get_data():
    # Lấy dữ liệu từ ESP32 (thay IP bằng IP thật của ESP32)
    try:
        esp_ip = request.args.get('esp_ip', '192.168.1.100')
        response = requests.get(f'http://{esp_ip}/data', timeout=5)
        data = response.json()
        
        # Lưu vào database
        sensor_data = SensorData(
            temperature=data['temperature'],
            humidity=data['humidity'],
            light=data['light'],
            air_quality=data['air_quality'],
            sound_level=data['sound_level'],
            evaluation=data['evaluation'],
            device_ip=esp_ip
        )
        db.session.add(sensor_data)
        db.session.commit()
        
        return jsonify(data)
    except:
        # Nếu không kết nối được ESP32, trả về dữ liệu mẫu
        return jsonify({
            'temperature': 25.5,
            'humidity': 65.2,
            'light': 450.0,
            'air_quality': 350.0,
            'sound_level': 55.0,
            'evaluation': 'Tốt',
            'led_state': True,
            'fan_state': False,
            'auto_mode': True
        })

# ================== API ĐIỀU KHIỂN ==================
@app.route('/api/control', methods=['POST'])
@login_required
def control_device():
    if current_user.role != 'admin':
        return jsonify({'error': 'Không có quyền'}), 403
    
    data = request.json
    esp_ip = data.get('esp_ip', '192.168.1.100')
    device = data.get('device')
    action = data.get('action')
    
    try:
        response = requests.get(f'http://{esp_ip}/control?device={device}&action={action}', timeout=5)
        return jsonify({'message': 'Thành công', 'response': response.text})
    except:
        return jsonify({'error': 'Không thể kết nối đến thiết bị'}), 500

# ================== LỊCH SỬ DỮ LIỆU ==================
@app.route('/history')
@login_required
def history():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    # Lọc dữ liệu
    device_ip = request.args.get('device_ip', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    query = SensorData.query
    
    if device_ip:
        query = query.filter_by(device_ip=device_ip)
    
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(SensorData.timestamp >= start)
        except:
            pass
    
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d')
            query = query.filter(SensorData.timestamp <= end)
        except:
            pass
    
    data = query.order_by(SensorData.timestamp.desc()).paginate(page=page, per_page=per_page)
    
    return render_template('history.html', data=data, user=current_user)

# ================== XUẤT PDF ==================
@app.route('/export/pdf')
@login_required
def export_pdf():
    # Tạo file PDF
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Tiêu đề
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, "BÁO CÁO CLASSGUARD")
    p.setFont("Helvetica", 12)
    p.drawString(50, height - 80, f"Ngày xuất: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    # Lấy dữ liệu gần nhất
    latest_data = SensorData.query.order_by(SensorData.timestamp.desc()).first()
    
    if latest_data:
        y = height - 120
        p.drawString(50, y, f"Nhiệt độ: {latest_data.temperature}°C")
        y -= 25
        p.drawString(50, y, f"Độ ẩm: {latest_data.humidity}%")
        y -= 25
        p.drawString(50, y, f"Ánh sáng: {latest_data.light} lux")
        y -= 25
        p.drawString(50, y, f"Chất lượng không khí: {latest_data.air_quality} ppm")
        y -= 25
        p.drawString(50, y, f"Mức âm thanh: {latest_data.sound_level} dB")
        y -= 25
        p.drawString(50, y, f"Đánh giá: {latest_data.evaluation}")
    
    p.save()
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True, download_name='classguard_report.pdf', mimetype='application/pdf')

# ================== QUẢN LÝ NGƯỜI DÙNG (chỉ admin) ==================
@app.route('/admin/users')
@login_required
def manage_users():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    users = User.query.all()
    return render_template('users.html', users=users, user=current_user)

# ================== TẠO DỮ LIỆU MẪU ==================
def create_sample_data():
    # Xóa database cũ
    db.drop_all()
    db.create_all()
    
    # Tạo user admin và viewer
    admin = User(username='admin', password='admin123', role='admin')
    viewer = User(username='xem', password='xem123', role='viewer')
    db.session.add(admin)
    db.session.add(viewer)
    
    # Tạo dữ liệu cảm biến mẫu
    import random
    from datetime import datetime, timedelta
    
    for i in range(100):
        timestamp = datetime.utcnow() - timedelta(hours=i)
        data = SensorData(
            timestamp=timestamp,
            temperature=random.uniform(20, 30),
            humidity=random.uniform(40, 80),
            light=random.uniform(200, 800),
            air_quality=random.uniform(200, 1000),
            sound_level=random.uniform(40, 90),
            evaluation=random.choice(['Xuất sắc', 'Tốt', 'Khá', 'Trung bình']),
            device_ip='192.168.1.100'
        )
        db.session.add(data)
    
    db.session.commit()
    print("Đã tạo dữ liệu mẫu!")

# ================== CHẠY ỨNG DỤNG ==================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Chỉ chạy dòng dưới lần đầu để tạo dữ liệu mẫu
        # create_sample_data()
    
    # Lấy port từ biến môi trường (cho fly.io)
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)