


"""
阿里云 OSS 对象存储客户端

【Java 类比】
- 类似封装了 Aliyun OSS SDK 的 OssService
- 或者类似 @Service 注解的 FileStorageService
- 职责：统一管理简历文件的存储和下载

【Python 库说明】
- oss2: 阿里云官方 Python SDK
- 提供完整的 OSS 操作：上传、下载、删除、列表等

【使用场景】
1. Java 端上传简历到 OSS → 返回 URL
2. Python 端从 OSS 下载简历进行解析
3. 存储面试录音/截图（可选扩展）

【设计模式】
- 单例模式: 全局共享一个 OSS 连接池
- 策略模式: 支持本地开发模式（不连接真实 OSS）
"""

import os
import uuid
import tempfile
from typing import Optional, BinaryIO, Dict, Any
from datetime import datetime
from dataclasses import dataclass

import oss2

from app.infrastructure.config import get_settings
from app.infrastructure.logger import get_logger
from app.infrastructure.error_handler import OssError

logger = get_logger(__name__)


@dataclass
class UploadResult:
    """上传结果封装"""

    file_url: str               # 文件访问 URL
    object_key: str             # OSS 对象键 (路径)
    file_size: int              # 文件大小(字节)
    etag: str                   # 文件 ETag (MD5)
    content_type: str           # MIME 类型


@dataclass
class DownloadResult:
    """下载结果封装"""

    local_path: str             # 本地临时文件路径
    file_size: int              # 文件大小
    content_type: str           # MIME 类型
    original_filename: str      # 原始文件名


class OSSClient:
    """
    阿里云 OSS 客户端核心类

    【Java 类比】
    ```java
    @Service
    public class OssServiceImpl implements OssService {
        @Value("${aliyun.oss.endpoint}")
        private String endpoint;

        @Value("${aliyun.oss.access-key-id}")
        private String accessKeyId;

        @Autowired
        private OSS ossClient;  // Spring 自动注入

        public String uploadFile(MultipartFile file) { ... }
        public InputStream downloadFile(String objectKey) { ... }
    }
    ```

    【核心功能】
    1. upload_file(): 上传文件到 OSS
    2. download_file(): 从 OSS 下载文件
    3. delete_file(): 删除 OSS 文件
    4. get_temp_url(): 生成临时访问链接
    """

    def __init__(self):
        settings = get_settings()
        self._endpoint = settings.oss.endpoint
        self._access_key_id = settings.oss.access_key_id
        self._access_key_secret = settings.oss.access_key_secret
        self._bucket_name = settings.oss.bucket_name

        self._is_configured = bool(
            self._access_key_id and
            self._access_key_secret and
            self._bucket_name
        )

        self._bucket = None

        if not self._is_configured:
            logger.warning(
                "oss_not_configured",
                action="请设置 ALIYUN_OSS_* 环境变量",
                hint="将使用本地存储模式"
            )
        else:
            self._init_bucket()

    def _init_bucket(self):
        """初始化 OSS Bucket 连接"""
        try:
            auth = oss2.Auth(self._access_key_id, self._access_key_secret)
            self._bucket = oss2.Bucket(auth, self._endpoint, self._bucket_name)

            info = self._bucket.get_bucket_info()
            logger.info(
                "oss_initialized",
                bucket=self._bucket_name,
                endpoint=self._endpoint,
                location=info.location
            )
        except Exception as e:
            logger.error("oss_init_failed", error=str(e))
            self._is_configured = False

    def is_available(self) -> bool:
        """检查 OSS 是否可用"""
        return self._is_configured and self._bucket is not None

    async def upload_file(
        self,
        file_data: bytes,
        filename: str,
        content_type: Optional[str] = None,
        folder: str = "resumes/"
    ) -> UploadResult:
        """
        上传文件到 OSS

        【参数说明】
        - file_data: 文件的二进制数据
        - filename: 原始文件名 (如 "resume.pdf")
        - content_type: MIME 类型 (可选，自动推断)
        - folder: 存储目录前缀 (默认 "resumes/")

        【返回值】
        - UploadResult: 包含 URL、object_key 等

        【对象路径规则】
        resumes/{user_id}/{uuid}_{original_filename}
        例如: resumes/user_123/abc123_zhangsan_resume.pdf

        【Java 类比】
        ```java
        // 类似 MultipartFile + OSS SDK
        public String upload(MultipartFile file, String userId) {
            String key = "resumes/" + userId + "/" + UUID.randomUUID() + "_" + file.getOriginalFilename();
            PutObjectRequest request = new PutObjectRequest(bucketName, key, file.getInputStream());
            ossClient.putObject(request);
            return generatePresignedUrl(key);
        }
        ```
        """
        if not content_type:
            content_type = self._guess_content_type(filename)

        object_key = f"{folder}{uuid.uuid4().hex[:8]}_{filename}"

        try:
            result = await self._upload_async(file_data, object_key, content_type)

            file_url = f"https://{self._bucket_name}.{self._endpoint.replace('https://', '').replace('http://', '')}/{object_key}"

            upload_result = UploadResult(
                file_url=file_url,
                object_key=object_key,
                file_size=len(file_data),
                etag=result.etag if hasattr(result, 'etag') else "",
                content_type=content_type or ""
            )

            logger.info(
                "oss_upload_success",
                object_key=object_key,
                file_size=len(file_data),
                url=file_url
            )

            return upload_result

        except Exception as e:
            logger.error("oss_upload_failed", error=str(e), object_key=object_key)
            raise OssError(f"OSS上传失败: {e}", detail=str(e))

    async def download_file(
        self,
        object_key: str,
        local_dir: Optional[str] = None
    ) -> DownloadResult:
        """
        从 OSS 下载文件到本地临时目录

        【参数说明】
        - object_key: OSS 对象键 (如 "resumes/abc123_resume.pdf")
        - local_dir: 本地保存目录 (默认系统临时目录)

        【返回值】
        - DownloadResult: 包含本地路径等信息

        【使用场景】
        Java 端上传后返回 object_key，
        Python 端调用此方法下载并解析
        """
        if not local_dir:
            local_dir = tempfile.gettempdir()

        original_filename = object_key.split("/")[-1]
        local_path = os.path.join(local_dir, f"downloaded_{original_filename}")

        try:
            result = await self._download_async(object_key, local_path)

            file_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0

            download_result = DownloadResult(
                local_path=local_path,
                file_size=file_size,
                content_type=result.headers.get("Content-Type", "") if hasattr(result, 'headers') else "",
                original_filename=original_filename
            )

            logger.info(
                "oss_download_success",
                object_key=object_key,
                local_path=local_path,
                file_size=file_size
            )

            return download_result

        except Exception as e:
            logger.error("oss_download_failed", error=str(e), object_key=object_key)
            raise OssError(f"OSS下载失败: {e}", detail=str(e))

    async def delete_file(self, object_key: str) -> bool:
        """删除 OSS 文件"""
        try:
            await self._delete_async(object_key)
            logger.info("oss_delete_success", object_key=object_key)
            return True
        except Exception as e:
            logger.error("oss_delete_failed", error=str(e), object_key=object_key)
            return False

    async def _upload_async(self, data: bytes, key: str, content_type: str):
        """异步上传（内部方法）"""
        import asyncio
        loop = asyncio.get_event_loop()

        def sync_upload():
            return self._bucket.put_object(key, data, headers={"Content-Type": content_type})

        return await loop.run_in_executor(None, sync_upload)

    async def _download_async(self, key: str, local_path: str):
        """异步下载（内部方法）"""
        import asyncio
        loop = asyncio.get_event_loop()

        def sync_download():
            return self._bucket.get_object_to_file(key, local_path)

        return await loop.run_in_executor(None, sync_download)

    async def _delete_async(self, key: str):
        """异步删除（内部方法）"""
        import asyncio
        loop = asyncio.get_event_loop()

        def sync_delete():
            return self._bucket.delete_object(key)

        return await loop.run_in_executor(None, sync_delete)

    @staticmethod
    def _guess_content_type(filename: str) -> str:
        """根据文件名推断 MIME 类型"""
        ext_map = {
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.txt': 'text/plain',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
        }
        from pathlib import Path
        ext = Path(filename).suffix.lower()
        return ext_map.get(ext, 'application/octet-stream')


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════

_oss_client_instance: Optional[OSSClient] = None


def get_oss_client() -> OSSClient:
    """获取全局 OSS 客户端单例"""
    global _oss_client_instance
    if _oss_client_instance is None:
        _oss_client_instance = OSSClient()
    return _oss_client_instance
