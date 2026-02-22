from __future__ import annotations

from urllib.parse import quote
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.core.db import get_session
from app.domain.models import Job
from app.domain.schemas import TARGET_OPTIONS
from app.services.prompt_store import (
    PROMPT_VARIABLE_TYPE_LABELS,
    PROMPT_VARIABLE_TYPES,
    get_prompt_descriptions,
    list_prompt_templates,
    list_prompt_variables_by_key,
    update_prompt_template,
    upsert_prompt_variable,
    delete_prompt_variable,
)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
router = APIRouter(tags=["ui"])


@router.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    jobs = session.exec(select(Job).order_by(Job.created_at.desc()).limit(50)).all()
    prompts_count = len(list_prompt_templates(session))
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "jobs": jobs,
            "default_targets": request.app.state.settings.default_targets_list,
            "target_options": TARGET_OPTIONS,
            "prompts_count": prompts_count,
        },
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(job_id: str, request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return templates.TemplateResponse(
        request=request,
        name="job.html",
        context={"job": job},
    )


@router.get("/prompts", response_class=HTMLResponse)
def prompt_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    prompts = list_prompt_templates(session)
    prompt_variables_by_key = list_prompt_variables_by_key(session)
    prompt_descriptions = get_prompt_descriptions()
    updated_key = request.query_params.get("updated")
    return templates.TemplateResponse(
        request=request,
        name="prompts.html",
        context={
            "prompts": prompts,
            "prompt_variables_by_key": prompt_variables_by_key,
            "prompt_variable_types": PROMPT_VARIABLE_TYPES,
            "prompt_variable_type_labels": PROMPT_VARIABLE_TYPE_LABELS,
            "updated_key": updated_key,
            "prompt_descriptions": prompt_descriptions,
        },
    )


@router.post("/prompts/{prompt_key}")
def update_prompt(
    prompt_key: str,
    content: str = Form(...),
    session: Session = Depends(get_session),
):
    update_prompt_template(session, key=prompt_key, content=content)
    encoded = quote(prompt_key, safe="")
    return RedirectResponse(url=f"/prompts?updated={encoded}", status_code=303)


@router.post("/prompts/{prompt_key}/variables/upsert")
def upsert_prompt_variable_route(
    prompt_key: str,
    name: str = Form(...),
    value_type: str = Form("INPUT_REQUIRED"),
    default_value: str = Form(""),
    description: str = Form(""),
    ai_instruction: str = Form(""),
    sort_order: str = Form("0"),
    session: Session = Depends(get_session),
):
    parsed_sort_order = 0
    try:
        parsed_sort_order = int(sort_order)
    except ValueError:
        parsed_sort_order = 0
    try:
        upsert_prompt_variable(
            session,
            prompt_key=prompt_key,
            name=name,
            value_type=value_type,
            default_value=default_value,
            description=description,
            ai_instruction=ai_instruction,
            sort_order=parsed_sort_order,
        )
    except ValueError:
        pass
    encoded = quote(prompt_key, safe="")
    return RedirectResponse(url=f"/prompts?updated={encoded}", status_code=303)


@router.post("/prompts/{prompt_key}/variables/delete")
def delete_prompt_variable_route(
    prompt_key: str,
    name: str = Form(...),
    session: Session = Depends(get_session),
):
    delete_prompt_variable(session, prompt_key=prompt_key, name=name)
    encoded = quote(prompt_key, safe="")
    return RedirectResponse(url=f"/prompts?updated={encoded}", status_code=303)
