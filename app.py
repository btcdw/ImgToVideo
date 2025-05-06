from flask import Flask, request, send_file, jsonify
from werkzeug.utils import secure_filename
import os
import tempfile
from PIL import Image
import cv2
import numpy as np
from pydub import AudioSegment
import shutil
import logging
import time

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB限制
TARGET_SIZE = (1080, 1920)
TARGET_RATIO = TARGET_SIZE[0] / TARGET_SIZE[1]

def resize_image(img):
    """调整图片尺寸"""
    img_width, img_height = img.size
    img_ratio = img_width / img_height
    if img_ratio > TARGET_RATIO:
        new_width = int(img_height * TARGET_RATIO)
        left = (img_width - new_width) // 2
        img = img.crop((left, 0, new_width + left, img_height))
    else:
        new_height = int(img_width / TARGET_RATIO)
        top = (img_height - new_height) // 2
        img = img.crop((0, top, img_width, new_height + top))
    return img.resize(TARGET_SIZE, Image.BICUBIC)

def generate_video(image_folder, switch_time, audio_path=None):
    """核心视频生成逻辑（修复音频路径）"""
    try:
        img_files = sorted([
            f for f in os.listdir(image_folder)
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))
        ])
        if not img_files:
            raise ValueError("未找到有效图片文件")
        
        fps = 1 / float(switch_time)
        temp_video_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp.mp4')
        fourcc = cv2.VideoWriter_fourcc(*'avc1')
        out = cv2.VideoWriter(temp_video_path, fourcc, fps, TARGET_SIZE, isColor=True)
        
        if not out.isOpened():
            raise RuntimeError("视频编码器初始化失败")
        
        for img_file in img_files:
            img_path = os.path.join(image_folder, img_file)
            with Image.open(img_path) as img:
                processed_img = resize_image(img)
                img_rgb = np.array(processed_img)
                img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
                out.write(img_bgr)
        out.release()
        logger.info(f"基础视频生成完成，路径:{temp_video_path}")

        # 修复：正确处理音频文件路径
        if audio_path:
            if not os.path.exists(audio_path):  # 新增：检查文件是否存在
                raise FileNotFoundError(f"音频文件未找到: {os.path.basename(audio_path)}")
            
            video_duration = len(img_files) * float(switch_time)
            try:
                audio = AudioSegment.from_file(audio_path)
                audio = audio[:int(video_duration * 1000)]
                temp_audio_path = os.path.join(app.config['UPLOAD_FOLDER'], 'audio.wav')
                audio.export(temp_audio_path, format='wav', parameters=['-b:a', '320k'])
                
                final_video_path = os.path.join(app.config['UPLOAD_FOLDER'], 'final.mp4')
                if os.system(f'ffmpeg -y -i {temp_video_path} -i {temp_audio_path} -c:v libx264 -crf 23 {final_video_path}') != 0:
                    raise RuntimeError("ffmpeg合并失败")
                return final_video_path
            except Exception as e:
                logger.error(f"音频处理失败: {str(e)}", exc_info=True)
                raise
        
        return temp_video_path

    except Exception as e:
        logger.error(f"视频生成失败: {str(e)}", exc_info=True)
        raise

# 根路由和请求处理函数（关键修复在音频保存部分）
@app.route('/generate', methods=['POST'])
def generate():
    try:
        logger.info("接收到视频生成请求")
        shutil.rmtree(app.config['UPLOAD_FOLDER'], ignore_errors=True)
        app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()  # 新建临时目录
        logger.debug(f"新临时目录: {app.config['UPLOAD_FOLDER']}")

        image_files = request.files.getlist('images')
        if not image_files:
            return jsonify(error="请选择图片"), 400

        image_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'images')
        os.makedirs(image_folder, exist_ok=True)
        for file in image_files:
            filename = secure_filename(file.filename)  # 处理文件名（包括中文）
            file.save(os.path.join(image_folder, filename))
        logger.debug(f"保存{len(image_files)}张图片到{image_folder}")

        switch_time = request.form.get('switch_time', '0.5')
        audio_file = request.files.get('audio')
        audio_path = None
        if audio_file:
            # 关键修复：正确保存音频文件到临时目录
            audio_filename = secure_filename(audio_file.filename)  # 处理中文文件名
            audio_path = os.path.join(app.config['UPLOAD_FOLDER'], audio_filename)
            audio_file.save(audio_path)  # 保存音频文件
            logger.debug(f"音频保存路径: {audio_path}")

        video_path = generate_video(image_folder, switch_time, audio_path)
        return send_file(video_path, as_attachment=True)

    except Exception as e:
        return jsonify(error=str(e)), 500

# 根路由保持不变
@app.route('/')
def index():
    try:
        return send_file('index.html')
    except FileNotFoundError:
        return "前端页面未找到", 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)