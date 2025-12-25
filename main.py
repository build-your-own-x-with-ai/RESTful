from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os

app = FastAPI(
    title="文件管理API",
    description="一个简单的RESTful API，用于上传、查看和删除文件",
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

# 确保上传目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/files", summary="上传文件")
async def upload_file(file: UploadFile = File(...)):
    """上传一个文件到服务器"""
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    # 检查文件是否已存在
    if os.path.exists(file_path):
        raise HTTPException(status_code=400, detail="文件已存在")
    
    # 保存文件
    try:
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")
    
    return {
        "filename": file.filename,
        "size": len(contents),
        "message": "文件上传成功"
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
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )

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
