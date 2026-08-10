from __future__ import annotations

from campus_job_desk.services.profile import ProfileService
from campus_job_desk.services.workflow import _representative_evidence_links


def test_representative_evidence_links_deduplicate_and_cap_resume_excerpts() -> None:
    text = """移动机器人任务规划原型：梳理任务下发、路径规划与异常处置流程，完成需求文档和产品原型。
工业智能巡检解决方案：围绕图像和设备日志设计巡检闭环，使用 Python 完成数据分析。
多源岗位决策工具：整合异构招聘表，设计来源追踪和字段冲突核验流程，完成可运行原型。
用户研究项目：完成访谈、需求分析和可用性测试，整理失败案例。"""
    profile = ProfileService().extract_text(text)
    fact_by_id = {fact.fact_id: fact for fact in profile.facts}

    links = _representative_evidence_links(fact_by_id, set(fact_by_id))

    assert len(links) == 3
    assert len({link["evidence_text"] for link in links}) == 3
    assert all(link["value"] not in {"产品", "数据", "Python"} for link in links)
