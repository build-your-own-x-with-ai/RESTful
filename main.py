from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import os
from PIL import Image
import io

# 尝试导入pyheif，如果失败则跳过HEIC格式处理
try:
    import pyheif
    HAS_PYHEIF = True
except ImportError:
    HAS_PYHEIF = False
    print("Warning: pyheif library not available, HEIC format support disabled")

app = FastAPI(
    title="文件管理API",
    description="一个简单的RESTful API，用于上传、查看和删除文件，支持文件格式转换",
    version="1.0.0"
)

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

# 确保上传目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 创建静态文件目录
STATIC_DIR = "./static"
os.makedirs(STATIC_DIR, exist_ok=True)

# 添加根路径路由，返回index.html
@app.get("/")
async def root():
    return HTMLResponse(open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8").read())

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 处理文本文件：转换为GBK编码
def process_text_file(contents, filename):
    """将文本文件转换为GBK编码"""
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
    return text.encode("gbk")

# 处理图片文件：转换为1bit BMP，调整尺寸
def process_image_file(contents, filename):
    """处理图片文件：转换为1bit BMP，调整尺寸为480x800"""
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
    
    return output.getvalue()

@app.post("/files", summary="上传文件")
async def upload_file(file: UploadFile = File(...)):
    """上传一个文件到服务器，并根据文件类型进行处理"""
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    
    # 读取文件内容
    try:
        contents = await file.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {str(e)}")
    
    # 根据文件类型进行处理
    processed_contents = contents
    processed_filename = filename
    
    if ext == ".txt":
        # 处理文本文件
        processed_contents = process_text_file(contents, filename)
    elif ext in IMAGE_EXTENSIONS:
        # 处理图片文件
        processed_contents = process_image_file(contents, filename)
        # 更改文件名为BMP格式
        processed_filename = os.path.splitext(filename)[0] + ".bmp"
    
    # 保存处理后的文件
    file_path = os.path.join(UPLOAD_DIR, processed_filename)
    
    # 检查文件是否已存在
    if os.path.exists(file_path):
        raise HTTPException(status_code=400, detail="文件已存在")
    
    try:
        with open(file_path, "wb") as f:
            f.write(processed_contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")
    
    return {
        "original_filename": filename,
        "processed_filename": processed_filename,
        "size": len(processed_contents),
        "message": "文件上传成功并已处理"
    }

@app.get("/files", summary="获取文件列表")
async def get_files():
    """获取服务器上所有文件的列表"""
    try:
        files = []
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(file_path):
                files.append({
                    "filename": filename,
                    "size": os.path.getsize(file_path),
                    "created_at": os.path.getctime(file_path)
                })
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
    
    if ext == ".txt":
        # 处理文本文件
        processed_contents = process_text_file(contents, filename)
    elif ext in IMAGE_EXTENSIONS or ext == ".bmp":
        # 处理图片文件
        processed_contents = process_image_file(contents, filename)
    
    # 更新文件
    try:
        with open(existing_file_path, "wb") as f:
            f.write(processed_contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件更新失败: {str(e)}")
    
    return {
        "filename": filename,
        "size": len(processed_contents),
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
        os.remove(file_path)
        return {"message": "文件删除成功", "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件删除失败: {str(e)}")
