"""
人设管理 API
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, List
from pathlib import Path

from ...engine.persona import get_persona, PersonaBuilder, PERSONAS_DIR

router = APIRouter()


class PersonaFileUpdate(BaseModel):
    """单个人设文档更新"""
    content: str


class PersonaUpdate(BaseModel):
    """完整人设更新"""
    files: Dict[str, str]  # {"SOUL.md": "...", "STYLE.md": "...", ...}


class PreviewRequest(BaseModel):
    message: str
    persona_name: str = "default"
    include_knowledge: bool = False


@router.get("/list")
async def list_personas():
    """获取所有人设列表"""
    personas = []
    if PERSONAS_DIR.exists():
        for d in PERSONAS_DIR.iterdir():
            if d.is_dir():
                soul_file = d / "SOUL.md"
                personas.append({
                    "name": d.name,
                    "has_soul": soul_file.exists(),
                    "files": [f.name for f in d.iterdir() if f.suffix == ".md"],
                })
    return {"personas": personas}


@router.get("/{persona_name}")
async def get_persona(persona_name: str):
    """获取人设文档内容"""
    try:
        builder = PersonaBuilder(persona_name).load_from_files()
        return {
            "name": persona_name,
            "files": builder.to_dict(),
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{persona_name}/file/{filename}")
async def update_persona_file(persona_name: str, filename: str, update: PersonaFileUpdate):
    """更新单个人设文件"""
    valid_files = {"SOUL.md", "STYLE.md", "SKILL.md", "MEMORY.md", "RULES.md"}
    if filename not in valid_files:
        raise HTTPException(status_code=400, detail=f"Invalid file: {filename}")

    persona_dir = PERSONAS_DIR / persona_name
    persona_dir.mkdir(parents=True, exist_ok=True)

    filepath = persona_dir / filename
    filepath.write_text(update.content, encoding="utf-8")

    # 刷新全局 Persona 缓存
    global _default_persona
    from server import main
    if hasattr(main, 'engine') and main.engine:
        main.engine.persona.reload()

    return {"status": "ok", "file": filename}


@router.put("/{persona_name}")
async def update_persona(persona_name: str, update: PersonaUpdate):
    """更新完整人设"""
    persona_dir = PERSONAS_DIR / persona_name
    persona_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in update.files.items():
        filepath = persona_dir / filename
        filepath.write_text(content, encoding="utf-8")

    # 刷新
    from server import main
    if hasattr(main, 'engine') and main.engine:
        main.engine.persona.reload()

    return {"status": "ok", "name": persona_name}


@router.post("/preview")
async def preview_persona(req: PreviewRequest):
    """预览人设效果 - 发送测试消息"""
    from server import main

    if not main.engine:
        raise HTTPException(status_code=503, detail="Engine not ready")

    # 临时使用指定人设
    original = main.engine.persona
    if req.persona_name != original.persona_name:
        main.engine.persona = get_persona(req.persona_name)
        reply = await main.engine.test_persona(req.message)
        main.engine.persona = original
    else:
        reply = await main.engine.test_persona(req.message)

    return {
        "message": req.message,
        "reply": reply,
        "persona": req.persona_name,
    }


@router.get("/{persona_name}/compile")
async def compile_prompt(persona_name: str):
    """查看编译后的 System Prompt"""
    try:
        builder = get_persona(persona_name)
        prompt = builder.build_system_prompt()
        return {
            "name": persona_name,
            "prompt": prompt,
            "length": len(prompt),
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
