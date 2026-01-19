# Sử dụng Python 3.9
FROM python:3.9-slim

# Cài đặt các phụ thuộc hệ thống
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Tạo thư mục làm việc
WORKDIR /app

# Sao chép requirements và cài đặt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn
COPY . .

# Chạy ứng dụng
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "app:app"]