from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import os
from PIL import Image
import io
import datetime
import json
import requests

# 尝试导入pyheif，如果失败则跳过HEIC格式处理
try:
    import pyheif
    HAS_PYHEIF = True
except ImportError:
    HAS_PYHEIF = False
    print("Warning: pyheif library not available, HEIC format support disabled")

from fastapi.openapi.docs import get_swagger_ui_html

app = FastAPI(
    title="文件管理API",
    description="一个简单的RESTful API，用于上传、查看和删除文件，支持文件格式转换",
    version="1.0.0",
    openapi_url="/openapi.json",
    docs_url=None,  # Disable default docs
    redoc_url=None,  # Disable default redoc
)

# Custom docs using a different Swagger UI version
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        swagger_js_url="https://unpkg.com/swagger-ui-dist@4/swagger-ui-bundle.js",
        swagger_css_url="https://unpkg.com/swagger-ui-dist@4/swagger-ui.css",
        swagger_favicon_url="https://fastapi.tiangolo.com/img/favicon.png",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
    )

@app.get("/docs/oauth2-redirect", include_in_schema=False)
async def swagger_ui_redirect():
    from fastapi.openapi.docs import get_swagger_ui_oauth2_redirect_html
    return get_swagger_ui_oauth2_redirect_html()

# 自定义API文档页面
@app.get("/api-docs", include_in_schema=False)
async def api_docs():
    return HTMLResponse(open(os.path.join(STATIC_DIR, "api-docs.html"), encoding="utf-8").read())

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，生产环境应限制为特定域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 文件存储路径
UPLOAD_DIR = "./uploads"

# 目标分辨率
TARGET_WIDTH = 480
TARGET_HEIGHT = 800

# 支持的图片格式
IMAGE_EXTENSIONS = {".bmp", ".png", ".webp", ".heic", ".jpg", ".jpeg"}

# 文件元数据存储路径
METADATA_FILE = os.path.join(UPLOAD_DIR, "metadata.json")

# 确保上传目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 创建静态文件目录
STATIC_DIR = "./static"
os.makedirs(STATIC_DIR, exist_ok=True)

# 创建缩略图目录
os.makedirs(os.path.join(UPLOAD_DIR, "thumbs"), exist_ok=True)

# 加载文件元数据
def load_metadata():
    """加载文件元数据"""
    if not os.path.exists(METADATA_FILE):
        return {}
    try:
        with open(METADATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# 保存文件元数据
def save_metadata(metadata):
    """保存文件元数据"""
    try:
        with open(METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存元数据失败: {str(e)}")

# 添加根路径路由，返回index.html
@app.get("/")
async def root():
    return HTMLResponse(open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8").read())

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 处理文本文件：转换为GBK编码并生成缩略图
def process_text_file(contents, filename):
    """将文本文件转换为GBK编码并生成缩略图"""
    try:
        # 尝试以UTF-8解码
        text = contents.decode("utf-8")
    except UnicodeDecodeError:
        try:
            # 尝试以GBK解码
            text = contents.decode("gbk")
        except UnicodeDecodeError:
            # 如果都失败，使用Latin-1解码
            text = contents.decode("latin-1")
    
    # 以GBK编码保存
    processed_contents = text.encode("gbk")
    
    # 生成文本文件的缩略图
    thumb_size = (150, 150)  # 缩略图尺寸
    
    # 创建一个新的150x150像素的白色图像
    from PIL import ImageDraw, ImageFont
    import io
    
    image = Image.new('L', thumb_size, color=255)  # 创建白色灰度图像
    draw = ImageDraw.Draw(image)
    
    # 使用默认字体
    try:
        font = ImageFont.load_default()
    except Exception:
        # 如果没有默认字体，使用位图字体
        font = ImageFont.truetype("/System/Library/Fonts/Monaco.ttf", 12) if os.name == "posix" else ImageFont.load_default()
    
    # 计算文本位置
    margin = 5
    line_height = 15
    max_lines = 9  # 150高度，15行高，9行
    
    # 显示文件名和前几行内容
    lines = [f"{filename}"] + text.splitlines()[:max_lines-1]
    
    for i, line in enumerate(lines):
        y = margin + i * line_height
        draw.text((margin, y), line, fill=0, font=font)
    
    # 转换为1bit BMP
    thumb_bmp = image.point(lambda x: 0 if x < 128 else 255, '1')
    
    # 保存缩略图
    thumb_dir = os.path.join(UPLOAD_DIR, "thumbs")
    os.makedirs(thumb_dir, exist_ok=True)
    # 确保缩略图使用.bmp扩展名
    thumb_filename = os.path.splitext(filename)[0] + ".bmp"
    thumb_path = os.path.join(thumb_dir, thumb_filename)
    thumb_bmp.save(thumb_path, format="BMP")
    
    return processed_contents

# 处理图片文件：转换为1bit BMP，调整尺寸
def process_image_file(contents, filename):
    """处理图片文件：转换为1bit BMP，调整尺寸为480x800，生成缩略图"""
    ext = os.path.splitext(filename)[1].lower()
    
    # 读取图片
    if ext == ".heic":
        # 处理HEIC格式
        if not HAS_PYHEIF:
            raise HTTPException(status_code=415, detail="HEIC format support is disabled")
        heif_file = pyheif.read(contents)
        image = Image.frombytes(
            heif_file.mode,
            heif_file.size,
            heif_file.data,
            "raw",
            heif_file.mode,
            heif_file.stride,
        )
    else:
        # 处理其他图片格式
        image = Image.open(io.BytesIO(contents))
    
    # 转换为RGB模式
    if image.mode != "RGB":
        image = image.convert("RGB")
    
    # 调整尺寸
    width, height = image.size
    
    # 计算新尺寸，保持宽高比
    if width > height:
        # 横屏图片，以高度为基准
        new_height = min(height, TARGET_HEIGHT)
        new_width = int((new_height / height) * width)
        if new_width > TARGET_WIDTH:
            new_width = TARGET_WIDTH
            new_height = int((new_width / width) * height)
    else:
        # 竖屏图片，以宽度为基准
        new_width = min(width, TARGET_WIDTH)
        new_height = int((new_width / width) * height)
        if new_height > TARGET_HEIGHT:
            new_height = TARGET_HEIGHT
            new_width = int((new_height / height) * width)
    
    # 调整图片尺寸
    resized_image = image.resize((new_width, new_height), Image.LANCZOS)
    
    # 转换为灰度图像
    gray_image = resized_image.convert("L")
    
    # 使用自适应阈值进行二值化处理，提高对比度
    bmp_image = gray_image.point(lambda x: 0 if x < 128 else 255, '1')
    
    # 保存到字节流
    output = io.BytesIO()
    bmp_image.save(output, format="BMP")
    output.seek(0)
    
    # 生成缩略图
    thumb_size = (150, 150)  # 缩略图尺寸
    thumbnail = image.copy()
    thumbnail.thumbnail(thumb_size, Image.LANCZOS)  # 保持宽高比
    
    # 转换为灰度图
    thumb_gray = thumbnail.convert("L")
    
    # 转换为1bit BMP
    thumb_bmp = thumb_gray.point(lambda x: 0 if x < 128 else 255, '1')
    
    # 保存缩略图
    thumb_dir = os.path.join(UPLOAD_DIR, "thumbs")
    os.makedirs(thumb_dir, exist_ok=True)
    thumb_filename = os.path.splitext(filename)[0] + ".bmp"
    thumb_path = os.path.join(thumb_dir, thumb_filename)
    thumb_bmp.save(thumb_path, format="BMP")
    
    return output.getvalue()

@app.post("/files", summary="上传文件")
async def upload_file(file: UploadFile = File(...)):
    """上传一个文件到服务器，并根据文件类型进行处理"""
    original_filename = file.filename
    ext = os.path.splitext(original_filename)[1].lower()
    
    # 读取文件内容
    try:
        contents = await file.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {str(e)}")
    
    # 根据文件类型进行处理
    processed_contents = contents
    
    # 生成基于时间戳的唯一文件名
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    
    if ext == ".txt":
        # 处理文本文件
        processed_contents = process_text_file(contents, original_filename)
        # 生成时间戳文件名
        processed_filename = f"{timestamp}.txt"
        file_type = "text/plain"
    elif ext in IMAGE_EXTENSIONS:
        # 处理图片文件
        # 先获取原始文件的处理结果
        processed_contents = process_image_file(contents, original_filename)
        # 生成时间戳文件名，统一为BMP格式
        processed_filename = f"{timestamp}.bmp"
        file_type = "image/bmp"
    else:
        # 其他文件类型，直接使用时间戳文件名
        processed_filename = f"{timestamp}{ext}"
        file_type = "application/octet-stream"
    
    # 保存处理后的文件
    file_path = os.path.join(UPLOAD_DIR, processed_filename)
    
    try:
        with open(file_path, "wb") as f:
            f.write(processed_contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")
    
    # 更新缩略图文件名（如果是图片或文本文件）
    if ext in IMAGE_EXTENSIONS or ext == ".txt":
        # 确保缩略图使用.bmp扩展名
        if ext in IMAGE_EXTENSIONS:
            # 图片文件的缩略图使用与主文件相同的扩展名（已统一为.bmp）
            new_thumb_path = os.path.join(UPLOAD_DIR, "thumbs", processed_filename)
            # 从处理后的图片重新生成缩略图
            image = Image.open(io.BytesIO(processed_contents))
            thumb_size = (150, 150)  # 缩略图尺寸
            thumbnail = image.copy()
            thumbnail.thumbnail(thumb_size, Image.LANCZOS)  # 保持宽高比
            # 转换为灰度图
            thumb_gray = thumbnail.convert("L")
            # 转换为1bit BMP
            thumb_bmp = thumb_gray.point(lambda x: 0 if x < 128 else 255, '1')
            # 保存缩略图
            thumb_bmp.save(new_thumb_path, format="BMP")
            # 删除原始缩略图（如果存在）
            old_thumb_path = os.path.join(UPLOAD_DIR, "thumbs", os.path.splitext(original_filename)[0] + ".bmp")
            if os.path.exists(old_thumb_path) and old_thumb_path != new_thumb_path:
                os.remove(old_thumb_path)
        elif ext == ".txt":
            # 文本文件的缩略图使用.bmp扩展名
            thumb_processed_filename = os.path.splitext(processed_filename)[0] + ".bmp"
            new_thumb_path = os.path.join(UPLOAD_DIR, "thumbs", thumb_processed_filename)
            # 获取生成的缩略图路径（使用原始文件名生成的）
            generated_thumb_path = os.path.join(UPLOAD_DIR, "thumbs", os.path.splitext(original_filename)[0] + ".bmp")
            if os.path.exists(generated_thumb_path):
                # 如果生成的缩略图路径和新路径不同，才需要重命名
                if generated_thumb_path != new_thumb_path:
                    os.rename(generated_thumb_path, new_thumb_path)
            else:
                # 如果生成的缩略图不存在，重新生成
                # 解码文本内容
                try:
                    # 尝试以GBK解码（因为文本文件已转换为GBK）
                    text = processed_contents.decode("gbk")
                except UnicodeDecodeError:
                    text = "无法解析文本"
                
                # 生成新的文本缩略图
                from PIL import ImageDraw, ImageFont
                
                image = Image.new('L', (150, 150), color=255)  # 创建白色灰度图像
                draw = ImageDraw.Draw(image)
                
                # 使用默认字体
                try:
                    font = ImageFont.load_default()
                except Exception:
                    font = ImageFont.truetype("/System/Library/Fonts/Monaco.ttf", 12) if os.name == "posix" else ImageFont.load_default()
                
                # 计算文本位置
                margin = 5
                line_height = 15
                max_lines = 9  # 150高度，15行高，9行
                
                # 显示文件名和前几行内容
                lines = [f"{processed_filename}"] + text.splitlines()[:max_lines-1]
                
                for i, line in enumerate(lines):
                    y = margin + i * line_height
                    draw.text((margin, y), line, fill=0, font=font)
                
                # 转换为1bit BMP
                thumb_bmp = image.point(lambda x: 0 if x < 128 else 255, '1')
                # 保存缩略图
                thumb_bmp.save(new_thumb_path, format="BMP")
    
    # 保存文件元数据
    metadata = load_metadata()
    file_metadata = {
        "original_filename": original_filename,
        "processed_filename": processed_filename,
        "size": len(processed_contents),
        "filetype": file_type,
        "upload_time": datetime.datetime.now().isoformat(),
        "is_image": ext in IMAGE_EXTENSIONS,
        "has_thumbnail": ext in IMAGE_EXTENSIONS or ext == ".txt"
    }
    metadata[processed_filename] = file_metadata
    save_metadata(metadata)
    
    # 生成缩略图URL
    if ext in IMAGE_EXTENSIONS or ext == ".txt":
        if ext == ".txt":
            # 文本文件的缩略图使用.bmp扩展名
            thumb_url = f"/files/thumbs/{os.path.splitext(processed_filename)[0]}.bmp"
        else:
            # 图片文件的缩略图使用与主文件相同的扩展名
            thumb_url = f"/files/thumbs/{processed_filename}"
    else:
        thumb_url = None
    
    return {
        "original_filename": original_filename,
        "processed_filename": processed_filename,
        "size": len(processed_contents),
        "filetype": file_type,
        "url": f"/files/{processed_filename}",
        "thumbnail": thumb_url,
        "message": "文件上传成功并已处理"
    }

@app.get("/files", summary="获取文件列表")
async def get_files():
    """获取服务器上所有文件的列表"""
    try:
        files = []
        metadata = load_metadata()
        
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            # 只返回txt和bmp文件
            if os.path.isfile(file_path) and filename.lower().endswith(('.txt', '.bmp')):
                file_info = {
                    "filename": filename,
                    "size": os.path.getsize(file_path),
                    "url": f"/files/{filename}"
                }
                
                # 如果有元数据，添加更多信息
                if filename in metadata:
                    file_info["original_filename"] = metadata[filename]["original_filename"]
                    file_info["filetype"] = metadata[filename]["filetype"]
                    file_info["upload_time"] = metadata[filename]["upload_time"]
                    
                    # 如果有缩略图，添加缩略图URL
                    if metadata[filename].get("has_thumbnail", False):
                        # 检查文件类型，确保txt文件的缩略图使用.bmp扩展名
                        if filename.lower().endswith(".txt"):
                            # 文本文件的缩略图使用.bmp扩展名
                            thumb_filename = os.path.splitext(filename)[0] + ".bmp"
                            file_info["thumbnail"] = f"/files/thumbs/{thumb_filename}"
                        else:
                            # 其他文件的缩略图使用与主文件相同的扩展名
                            file_info["thumbnail"] = f"/files/thumbs/{filename}"
                
                files.append(file_info)
        
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文件列表失败: {str(e)}")

@app.get("/files/{filename}", summary="获取单个文件")
async def get_file(filename: str):
    """根据文件名获取文件"""
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=400, detail="路径不是文件")
    
    # 根据文件类型设置不同的media_type
    if filename.lower().endswith(".txt"):
        # 文本文件使用text/plain类型，并指定GBK编码
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="text/plain; charset=gbk"
        )
    elif filename.lower().endswith(".bmp"):
        # BMP图片使用image/bmp类型
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="image/bmp"
        )
    else:
        # 其他文件使用默认类型
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/octet-stream"
        )

@app.get("/files/thumbs/{filename}", summary="获取缩略图")
async def get_thumbnail(filename: str):
    """根据文件名获取缩略图"""
    thumb_path = os.path.join(UPLOAD_DIR, "thumbs", filename)
    
    if not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail="缩略图不存在")
    
    if not os.path.isfile(thumb_path):
        raise HTTPException(status_code=400, detail="路径不是文件")
    
    # 返回缩略图
    return FileResponse(
        path=thumb_path,
        filename=filename,
        media_type="image/bmp"
    )

@app.put("/files/{filename}", summary="更新文件")
async def update_file(filename: str, file: UploadFile = File(...)):
    """更新已存在的文件，保持相同的文件名"""
    # 检查文件是否已存在
    existing_file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(existing_file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    
    if not os.path.isfile(existing_file_path):
        raise HTTPException(status_code=400, detail="路径不是文件")
    
    # 读取文件内容
    try:
        contents = await file.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {str(e)}")
    
    # 根据文件类型进行处理
    processed_contents = contents
    
    # 获取文件扩展名
    ext = os.path.splitext(filename)[1].lower()
    original_filename = file.filename
    
    if ext == ".txt":
        # 处理文本文件
        processed_contents = process_text_file(contents, original_filename)
        file_type = "text/plain"
    elif ext in IMAGE_EXTENSIONS or ext == ".bmp":
        # 处理图片文件
        processed_contents = process_image_file(contents, original_filename)
        file_type = "image/bmp"
    else:
        # 其他文件类型
        file_type = "application/octet-stream"
    
    # 更新文件
    try:
        with open(existing_file_path, "wb") as f:
            f.write(processed_contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件更新失败: {str(e)}")
    
    # 更新缩略图（如果是图片或文本文件）
    if ext in IMAGE_EXTENSIONS or ext == ".bmp" or ext == ".txt":
        if ext == ".txt":
            # 文本文件的缩略图使用.bmp扩展名
            thumb_filename = os.path.splitext(filename)[0] + ".bmp"
            thumb_path = os.path.join(UPLOAD_DIR, "thumbs", thumb_filename)
        else:
            # 其他文件的缩略图使用与主文件相同的扩展名
            thumb_path = os.path.join(UPLOAD_DIR, "thumbs", filename)
        
        if ext in IMAGE_EXTENSIONS or ext == ".bmp":
            # 处理图片文件的缩略图
            image = Image.open(io.BytesIO(processed_contents))
            thumb_size = (150, 150)  # 缩略图尺寸
            thumbnail = image.copy()
            thumbnail.thumbnail(thumb_size, Image.LANCZOS)  # 保持宽高比
            # 转换为灰度图
            thumb_gray = thumbnail.convert("L")
            # 转换为1bit BMP
            thumb_bmp = thumb_gray.point(lambda x: 0 if x < 128 else 255, '1')
            # 保存缩略图
            thumb_bmp.save(thumb_path, format="BMP")
        elif ext == ".txt":
            # 处理文本文件的缩略图
            # 解码文本内容
            try:
                # 尝试以GBK解码（因为文本文件已转换为GBK）
                text = processed_contents.decode("gbk")
            except UnicodeDecodeError:
                text = "无法解析文本"
            
            # 生成新的文本缩略图
            from PIL import ImageDraw, ImageFont
            
            image = Image.new('L', (150, 150), color=255)  # 创建白色灰度图像
            draw = ImageDraw.Draw(image)
            
            # 使用默认字体
            try:
                font = ImageFont.load_default()
            except Exception:
                font = ImageFont.truetype("/System/Library/Fonts/Monaco.ttf", 12) if os.name == "posix" else ImageFont.load_default()
            
            # 计算文本位置
            margin = 5
            line_height = 15
            max_lines = 9  # 150高度，15行高，9行
            
            # 显示文件名和前几行内容
            lines = [f"{filename}"] + text.splitlines()[:max_lines-1]
            
            for i, line in enumerate(lines):
                y = margin + i * line_height
                draw.text((margin, y), line, fill=0, font=font)
            
            # 转换为1bit BMP
            thumb_bmp = image.point(lambda x: 0 if x < 128 else 255, '1')
            # 保存缩略图
            thumb_bmp.save(thumb_path, format="BMP")
    
    # 更新文件元数据
    metadata = load_metadata()
    if filename in metadata:
        file_metadata = metadata[filename]
        file_metadata["size"] = len(processed_contents)
        file_metadata["filetype"] = file_type
        file_metadata["upload_time"] = datetime.datetime.now().isoformat()
        save_metadata(metadata)
    
    # 生成缩略图URL
    if ext in IMAGE_EXTENSIONS or ext == ".bmp" or ext == ".txt":
        if ext == ".txt":
            # 文本文件的缩略图使用.bmp扩展名
            thumb_url = f"/files/thumbs/{os.path.splitext(filename)[0]}.bmp"
        else:
            # 图片文件的缩略图使用与主文件相同的扩展名
            thumb_url = f"/files/thumbs/{filename}"
    else:
        thumb_url = None
    
    return {
        "original_filename": original_filename,
        "filename": filename,
        "size": len(processed_contents),
        "filetype": file_type,
        "url": f"/files/{filename}",
        "thumbnail": thumb_url,
        "message": "文件更新成功并已处理"
    }

@app.delete("/files/{filename}", summary="删除文件")
async def delete_file(filename: str):
    """根据文件名删除文件"""
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=400, detail="路径不是文件")
    
    try:
        # 删除文件
        os.remove(file_path)
        
        # 删除缩略图（如果存在）
        # 检查文件类型，确保txt文件的缩略图（.bmp扩展名）也被删除
        if filename.lower().endswith(".txt"):
            # 文本文件的缩略图使用.bmp扩展名
            thumb_filename = os.path.splitext(filename)[0] + ".bmp"
            thumb_path = os.path.join(UPLOAD_DIR, "thumbs", thumb_filename)
        else:
            # 其他文件的缩略图使用与主文件相同的扩展名
            thumb_path = os.path.join(UPLOAD_DIR, "thumbs", filename)
            
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
        
        # 删除元数据
        metadata = load_metadata()
        if filename in metadata:
            del metadata[filename]
            save_metadata(metadata)
        
        return {"message": "文件删除成功", "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件删除失败: {str(e)}")

@app.get("/wallpaper/new", summary="获取新壁纸")
async def get_new_wallpaper():
    """从网络获取新壁纸，转换为480x800 1Bit Bitmap格式并保存"""
    try:
        # 从Picsum Photos获取随机壁纸（使用免费的public API）
        wallpaper_url = "https://picsum.photos/1920/1080"
        response = requests.get(wallpaper_url, timeout=10)
        response.raise_for_status()
        
        # 读取图片内容
        wallpaper_content = response.content
        
        # 使用现有的图片处理函数转换为480x800 1Bit Bitmap格式
        processed_wallpaper = process_image_file(wallpaper_content, "temp_wallpaper.jpg")
        
        # 固定壁纸文件名
        fixed_wallpaper_name = "wallpaper.bmp"
        wallpaper_path = os.path.join(UPLOAD_DIR, fixed_wallpaper_name)
        
        # 保存壁纸
        with open(wallpaper_path, "wb") as f:
            f.write(processed_wallpaper)
        
        # 重命名缩略图为正确的名称
        old_thumb_path = os.path.join(UPLOAD_DIR, "thumbs", "temp_wallpaper.bmp")
        new_thumb_path = os.path.join(UPLOAD_DIR, "thumbs", fixed_wallpaper_name)
        if os.path.exists(old_thumb_path):
            os.rename(old_thumb_path, new_thumb_path)
        
        # 保存壁纸元数据
        metadata = load_metadata()
        wallpaper_metadata = {
            "original_filename": "wallpaper.jpg",
            "processed_filename": fixed_wallpaper_name,
            "size": len(processed_wallpaper),
            "filetype": "image/bmp",
            "upload_time": datetime.datetime.now().isoformat(),
            "is_image": True,
            "has_thumbnail": True
        }
        metadata[fixed_wallpaper_name] = wallpaper_metadata
        save_metadata(metadata)
        
        # 生成缩略图URL
        thumb_url = f"/files/thumbs/{fixed_wallpaper_name}"
        
        return {
            "filename": fixed_wallpaper_name,
            "url": f"/files/{fixed_wallpaper_name}",
            "thumbnail": thumb_url,
            "size": len(processed_wallpaper),
            "filetype": "image/bmp",
            "message": "新壁纸获取成功并已处理"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取新壁纸失败: {str(e)}")
