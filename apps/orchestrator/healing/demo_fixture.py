"""Explicitly SCRIPTED demo agent. Never selected as a fallback after an AI error."""
from .models import Diagnosis, RepairReport


class FixtureAgent:
    async def diagnose(self, logs: str) -> Diagnosis:
        return Diagnosis(summary="Scripted fixture: investigate zero-quantity quote",
                         root_cause="The fixture expects an unchecked division by quantity.", confidence=1)

    async def repair(self, sandbox, context: dict, emit) -> RepairReport:
        path = "apps/broken-app/main.py"
        files = await sandbox.read_files([path])
        source = files[path]
        needle = "    unit_price = 25\n"
        if needle not in source or "    discount_per_item = 10 / quantity" not in source:
            raise RuntimeError("Scripted fixture only supports the bundled original pricing scenario")
        source = source.replace("from fastapi import FastAPI, Query, Request",
                                "from fastapi import FastAPI, HTTPException, Query, Request")
        if "HTTPException" not in source:
            raise RuntimeError("Fixture source shape changed; use AGENT_MODE=openrouter")
        source = source.replace(needle, '    if quantity == 0:\n        raise HTTPException(status_code=400, '
                                'detail="Quantity must be greater than zero.")\n' + needle, 1)
        await sandbox.write_files({path: source})
        await emit("Scripted fixture applied; validation still requires actual sandbox tests", "info",
                   {"simulated": True, "files": [path]})
        return RepairReport(summary="Scripted fixture: validate quantity before calculating discount",
                            root_cause="Zero quantity reaches a division operation.", confidence=1,
                            correction="Reject zero quantity with HTTP 400.",
                            regression_tests=["test_zero_quantity_returns_400"],
                            validation_summary="Pending independent orchestrator validation",
                            files_changed=[path])
