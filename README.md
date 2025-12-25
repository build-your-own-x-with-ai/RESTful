# 文件管理 RESTful API

一个基于 FastAPI 的文件管理 API，支持文件上传、查看、删除功能，并对上传的文件进行自动处理。

## 功能特性

- **文件上传**：支持上传文本文件和图片文件
- **文件处理**：
  - TXT 文档：自动转换为 GBK 编码
  - 图片文件（BMP、PNG、WEBP、HEIC、JPG 等）：自动转换为 1bit BMP 格式
    - 竖屏分辨率：最大 480x800
    - 保持宽高比
    - 大于 480x800 的图片会被压缩到符合要求
    - 小于等于 480x800 的图片保持原样
- **文件管理**：支持查看文件列表、下载文件和删除文件
- **自动生成 API 文档**：使用 Swagger UI 可访问 http://localhost:8000/docs

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动服务

```bash
uvicorn main:app --reload
```

服务将在 http://localhost:8000 启动。

## CURL 使用说明

### 1. 上传文件

#### 上传文本文件

```bash
curl -X POST "http://localhost:8000/files" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@your_file.txt"
```

#### 上传图片文件

```bash
curl -X POST "http://localhost:8000/files" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@your_image.png"
```

### 2. 获取文件列表

```bash
curl -X GET "http://localhost:8000/files"
```

### 3. 下载文件

```bash
curl -X GET "http://localhost:8000/files/filename.txt" -o downloaded_file.txt
```

### 4. 删除文件

```bash
curl -X DELETE "http://localhost:8000/files/filename.txt"
```

## API 端点

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | /files | 上传文件 |
| GET | /files | 获取文件列表 |
| GET | /files/{filename} | 下载指定文件 |
| DELETE | /files/{filename} | 删除指定文件 |

## 项目结构

```
.
├── main.py          # API 主文件
├── requirements.txt # 项目依赖
├── README.md        # 项目说明
└── uploads/         # 文件存储目录
```

## 注意事项

1. 上传的文件会自动保存在 `uploads/` 目录下
2. 文本文件会被转换为 GBK 编码
3. 图片文件会被转换为 1bit BMP 格式
4. HEIC 格式支持需要 pyheif 库，如果安装失败，HEIC 格式将被禁用
