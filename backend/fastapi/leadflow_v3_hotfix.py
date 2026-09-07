"""Lead Flow v3 runtime hotfix.

Keeps the complete-pipeline app intact while correcting automation classification so
it can be evaluated safely during the same processing step that assigns score.
"""
from backend.fastapi import leadflow_v3 as base


def automation(item):
    score = int(item.get("score") or 0)
    ready = bool(item.get("verified_business") and (item.get("phone") or item.get("email")))
    if score >= 75 and ready:
        action = "PRIORITY_OUTREACH"
    elif score >= 55 and ready:
        action = "OUTREACH"
    elif score >= 35:
        action = "RESEARCH_MORE"
    else:
        action = "NURTURE"
    return {
        "action": action,
        "outreach_ready": ready,
        "next_action": "Contact using verified public channel" if ready else "Find an additional public contact source",
        "reason": "High confirmed opportunity gaps with verified business identity" if ready and score >= 55 else "Needs additional evidence before outreach",
    }


base.automation = automation
app = base.app
