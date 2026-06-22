"""
AI 模型配置 API — API Key 加密存储在数据库中
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.base import get_db
from ...db.models import LLMProviderRecord
from ...crypto_utils import encrypt_api_key, decrypt_api_key, mask_api_key

router = APIRouter()


class ModelConfigRequest(BaseModel):
    name: str
    provider: str  # anthropic | openai | openai_compat
    model_id: str
    api_key: str                    # 明文传入，自动加密存储
    api_base: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    weight: int = 100
    enabled: bool = True
    tags: List[str] = ["default"]


class ModelUpdateRequest(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model_id: Optional[str] = None
    api_key: Optional[str] = None    # 明文传入，为空表示不修改
    api_base: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    weight: Optional[int] = None
    enabled: Optional[bool] = None
    tags: Optional[List[str]] = None


def _get_router():
    """延迟获取 LLM Router"""
    from server import main
    return main.llm_router


@router.get("/")
async def list_models(db: AsyncSession = Depends(get_db)):
    """获取所有模型配置 (API Key 脱敏显示)"""
    result = await db.execute(
        select(LLMProviderRecord).order_by(LLMProviderRecord.name)
    )
    records = result.scalars().all()

    models = []
    for r in records:
        decrypted = decrypt_api_key(r.api_key or "")
        models.append({
            "name": r.name,
            "provider": r.provider,
            "model_id": r.model_id,
            "api_key": mask_api_key(decrypted),  # 脱敏: sk-ant-***...xxxx
            "api_key_configured": bool(decrypted),  # 是否已配置
            "api_base": r.api_base,
            "temperature": r.temperature,
            "max_tokens": r.max_tokens,
            "weight": r.weight,
            "enabled": r.enabled,
            "tags": r.tags or [],
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })

    return {"models": models}


@router.get("/status")
async def get_models_status():
    """获取模型运行状态"""
    router = _get_router()
    if not router:
        return {"status": "no router"}

    status = router.get_status()

    # 合并 DB 中的 enabled 状态
    return {"models": status}


@router.post("/")
async def add_model(model: ModelConfigRequest, db: AsyncSession = Depends(get_db)):
    """添加新模型 (API Key 自动加密存储)"""
    # 检查重名
    result = await db.execute(
        select(LLMProviderRecord).where(LLMProviderRecord.name == model.name)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"模型 '{model.name}' 已存在")

    record = LLMProviderRecord(
        name=model.name,
        provider=model.provider,
        model_id=model.model_id,
        api_key=encrypt_api_key(model.api_key) if model.api_key else "",
        api_base=model.api_base,
        temperature=model.temperature,
        max_tokens=model.max_tokens,
        weight=model.weight,
        enabled=model.enabled,
        tags=model.tags,
    )
    db.add(record)
    await db.commit()

    # 返回脱敏信息
    return {
        "status": "ok",
        "name": model.name,
        "api_key_configured": bool(model.api_key),
    }


@router.put("/{model_name}")
async def update_model(
    model_name: str,
    update: ModelUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新模型配置 (API Key 自动加密)"""
    result = await db.execute(
        select(LLMProviderRecord).where(LLMProviderRecord.name == model_name)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail=f"模型 '{model_name}' 不存在")

    # 更新字段
    if update.name is not None:
        record.name = update.name
    if update.provider is not None:
        record.provider = update.provider
    if update.model_id is not None:
        record.model_id = update.model_id
    if update.api_key is not None and update.api_key:
        # 只有传入了非空的 API Key 才更新
        record.api_key = encrypt_api_key(update.api_key)
    if update.api_base is not None:
        record.api_base = update.api_base
    if update.temperature is not None:
        record.temperature = update.temperature
    if update.max_tokens is not None:
        record.max_tokens = update.max_tokens
    if update.weight is not None:
        record.weight = update.weight
    if update.enabled is not None:
        record.enabled = update.enabled
    if update.tags is not None:
        record.tags = update.tags

    await db.commit()

    # API Key 有变更时重新加载 Router
    if update.api_key is not None and update.api_key:
        router = _get_router()
        if router:
            await router.reload_from_db(db)

    return {"status": "ok", "name": model_name}


@router.put("/{model_name}/toggle")
async def toggle_model(model_name: str, db: AsyncSession = Depends(get_db)):
    """快速切换模型启用状态"""
    result = await db.execute(
        select(LLMProviderRecord).where(LLMProviderRecord.name == model_name)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404)

    record.enabled = not record.enabled
    await db.commit()

    # 重新加载 Router
    router = _get_router()
    if router:
        await router.reload_from_db(db)

    return {"name": model_name, "enabled": record.enabled}


@router.delete("/{model_name}")
async def delete_model(model_name: str, db: AsyncSession = Depends(get_db)):
    """删除模型"""
    result = await db.execute(
        select(LLMProviderRecord).where(LLMProviderRecord.name == model_name)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404)

    await db.delete(record)
    await db.commit()

    # 重新加载 Router
    router = _get_router()
    if router:
        await router.reload_from_db(db)

    return {"deleted": model_name}


@router.post("/{model_name}/test")
async def test_model(model_name: str, db: AsyncSession = Depends(get_db)):
    """测试模型连通性"""
    router = _get_router()
    if not router:
        raise HTTPException(status_code=503, detail="Router not available")

    # 从 DB 获取加密的 Key 解密后测试
    result = await db.execute(
        select(LLMProviderRecord).where(LLMProviderRecord.name == model_name)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404)

    api_key = decrypt_api_key(record.api_key or "")
    if not api_key:
        return {
            "model": model_name,
            "status": "no_key",
            "error": "未配置 API Key，请在 GUI 中设置",
        }

    # 临时注册并测试
    from ...config import ModelConfig
    from ...llm.base import LLMRequest

    config = ModelConfig(
        name=record.name,
        provider=record.provider,
        model_id=record.model_id,
        api_key=api_key,
        api_base=record.api_base,
        temperature=record.temperature,
        max_tokens=record.max_tokens,
        tags=record.tags or ["default"],
    )

    try:
        temp_provider = router.register(config)
        if not temp_provider:
            return {"model": model_name, "status": "error", "error": "无法创建 Provider"}

        result_text = await temp_provider.chat(LLMRequest(
            messages=[{"role": "user", "content": "回复 OK"}],
            max_tokens=20,
        ))
        return {
            "model": model_name,
            "status": "ok",
            "response": result_text[:200],
        }
    except Exception as e:
        return {
            "model": model_name,
            "status": "error",
            "error": str(e)[:300],
        }


@router.post("/reload")
async def reload_router(db: AsyncSession = Depends(get_db)):
    """重新加载 LLM Router (从 DB 读取最新配置)"""
    router = _get_router()
    if not router:
        raise HTTPException(status_code=503)

    status = await router.reload_from_db(db)
    return {"status": "ok", "models": status}
