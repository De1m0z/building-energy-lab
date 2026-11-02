"""Run with a separate test server; all imported fixtures are simulated data."""
import csv
import io
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797"
AXE = Path(sys.argv[2]) if len(sys.argv) > 2 else None
OUTPUT = Path(__file__).resolve().parents[1] / "verification"
OUTPUT.mkdir(exist_ok=True)
MOTION_PROBE = """
window.__motionCalls = [];
const originalAnimate = Element.prototype.animate;
Element.prototype.animate = function(frames, options) {
  window.__motionCalls.push({ target: this.id || this.className, duration: options.duration, delay: options.delay || 0, properties: Object.keys(frames[0]) });
  return originalAnimate.call(this, frames, options);
};
"""


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="chrome", headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    context.add_init_script(MOTION_PROBE)
    external_requests, errors = [], []

    def local_only(route):
        if urlsplit(route.request.url).hostname not in {"localhost", "127.0.0.1"}:
            external_requests.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    context.route("**/*", local_only)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(BASE)
    page.wait_for_load_state("networkidle")
    expect(page.locator("#heating-value")).to_have_text("15.96")
    expect(page.locator("#prediction-record")).to_contain_text("HELD OUT")
    initial_motion = page.evaluate("window.__motionCalls")
    assert initial_motion and all(call["duration"] == 200 and call["delay"] <= 60 for call in initial_motion)
    assert all(set(call["properties"]) <= {"opacity", "transform"} for call in initial_motion)
    page.screenshot(path=str(OUTPUT / "desktop-predict.png"), full_page=True, animations="disabled")

    page.locator("#predict-form-X7").select_option("0.25")
    expect(page.locator("#prediction-output")).to_be_hidden()
    expect(page.locator("#predict-form-X8")).to_be_enabled()
    page.get_by_role("button", name="Run predictions").click()
    expect(page.locator("#prediction-output")).to_be_visible()
    page.get_by_text("Show simulated reference", exact=True).click()
    expect(page.locator("#prediction-reference")).to_contain_text("Simulated heating")
    with page.expect_download() as downloaded:
        page.get_by_role("button", name="Export predictions").click()
    downloaded.value.save_as(OUTPUT / "prediction-export.csv")
    assert len(list(csv.reader((OUTPUT / "prediction-export.csv").open()))) == 4

    page.get_by_role("link", name="Compare designs", exact=True).click()
    page.get_by_role("button", name="Compare designs", exact=False).click()
    expect(page.locator("#compare-output")).to_be_visible()
    expect(page.locator("#comparison-table tbody tr")).to_have_count(3)
    with page.expect_download() as downloaded:
        page.get_by_role("button", name="Export comparison").click()
    downloaded.value.save_as(OUTPUT / "comparison-export.csv")
    assert "B minus A" in (OUTPUT / "comparison-export.csv").read_text()
    page.screenshot(path=str(OUTPUT / "desktop-compare.png"), full_page=True, animations="disabled")

    page.get_by_role("link", name="Study results", exact=True).click()
    expect(page.locator("#study-content")).to_be_visible()
    expect(page.locator("#study-metrics tbody tr")).to_have_count(7)
    page.get_by_label("Cooling", exact=True).check()
    expect(page.locator("#glazing-table")).to_contain_text("22.58")
    page.get_by_text("Reproducibility, paper comparison, and sources", exact=False).click()
    expect(page.locator("#paper-comparison")).to_contain_text("Matches")
    assert page.locator("#paper-comparison").inner_text().count("Matches") == 4
    page.screenshot(path=str(OUTPUT / "desktop-study.png"), full_page=True, animations="disabled")

    page.get_by_role("link", name="Test your dataset", exact=False).click()
    expect(page.locator('#dataset-steps [aria-current="step"]')).to_have_attribute("data-step", "0")
    page.get_by_role("button", name="Try simulated example", exact=True).click()
    expect(page.locator("#dataset-name")).to_have_text("SIMULATED-demo-data.csv")
    expect(page.locator("#mapping-completeness")).to_have_text("8 of 8 mapped")
    expect(page.locator("#dataset-source")).to_have_value("simulation")
    expect(page.locator('#dataset-steps [aria-current="step"]')).to_have_attribute("data-step", "1")
    source = context.request.get(BASE + "/api/template/example").body()
    transfer = page.evaluate_handle("source => { const data = new DataTransfer(); data.items.add(new File([source], 'SIMULATED-browser-example.csv', { type: 'text/csv' })); return data; }", source.decode())
    page.locator(".file-picker").dispatch_event("dragenter", {"dataTransfer": transfer})
    expect(page.locator(".file-picker")).to_have_class("file-picker is-dragging")
    page.locator(".file-picker").dispatch_event("drop", {"dataTransfer": transfer})
    expect(page.locator("#file-picker-label")).to_have_text("SIMULATED-browser-example.csv")
    page.get_by_role("button", name="Upload & inspect").click()
    expect(page.locator("#dataset-name")).to_have_text("SIMULATED-browser-example.csv")
    expect(page.locator("#map-X1")).to_have_value("X1")
    page.get_by_role("button", name="Validate mapping").click()
    expect(page.locator("#evaluate-button")).to_be_enabled()
    page.get_by_role("button", name="Run dataset test").click()
    expect(page.locator("#dataset-results")).to_be_visible()
    expect(page.locator("#evaluation-mode")).to_have_text("Predictions only")
    expect(page.locator('#dataset-steps [aria-current="step"]')).to_have_attribute("data-step", "2")

    # Deliberately omitted reference mappings must remain omitted when reopening a saved import.
    page.locator("#map-Y1").select_option("")
    page.locator("#map-Y2").select_option("")
    page.get_by_role("button", name="Validate mapping").click()
    expect(page.locator("#evaluate-button")).to_be_enabled()
    page.get_by_role("button", name="Run dataset test").click()
    expect(page.locator("#dataset-results")).to_be_visible()
    page.get_by_role("button", name="Open SIMULATED-browser-example.csv").click()
    expect(page.locator("#map-Y1")).to_have_value("")
    expect(page.locator("#map-Y2")).to_have_value("")
    expect(page.locator("#reference-options")).not_to_have_attribute("open", "")
    page.locator("#reference-options summary").click()
    page.locator("#map-Y1").select_option("Y1")
    page.locator("#map-Y2").select_option("Y2")

    page.locator("#dataset-source").select_option("simulation")
    page.locator("#response-units").fill("Original dataset load units")
    page.locator("#response-definition").fill("UCI Energy Efficiency simulated Y1 and Y2")
    page.locator("#confirm-comparable").check()
    expect(page.locator("#dataset-results")).to_be_hidden()
    page.get_by_role("button", name="Validate mapping").click()
    expect(page.locator("#evaluate-button")).to_be_enabled()
    page.get_by_role("button", name="Run dataset test").click()
    expect(page.locator("#evaluation-mode")).to_have_text("Reference evaluation")
    expect(page.locator("#dataset-score-table tbody tr")).to_have_count(6)
    expect(page.locator("#dataset-plots svg")).to_have_count(4)
    with page.expect_download() as downloaded:
        page.get_by_role("link", name="Download row-level CSV").click()
    downloaded.value.save_as(OUTPUT / "dataset-export.csv")
    assert len(pd.read_csv(OUTPUT / "dataset-export.csv")) == 4
    with page.expect_download() as downloaded:
        page.get_by_role("button", name="Download JSON report").click()
    downloaded.value.save_as(OUTPUT / "dataset-report.json")
    report = json.loads((OUTPUT / "dataset-report.json").read_text())
    assert len(report["metrics"]) == 6
    page.screenshot(path=str(OUTPUT / "desktop-dataset-results.png"), full_page=True, animations="disabled")

    page.reload()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Open SIMULATED-browser-example.csv").click()
    expect(page.locator("#evaluation-mode")).to_have_text("Reference evaluation")
    frame = pd.read_csv(io.BytesIO(source))
    frame.loc[0, "X6"] = 99
    page.locator("#dataset-file").set_input_files({"name": "SIMULATED-invalid-row.csv", "mimeType": "text/csv", "buffer": frame.to_csv(index=False).encode()})
    page.get_by_role("button", name="Upload & inspect").click()
    expect(page.locator("#dataset-name")).to_have_text("SIMULATED-invalid-row.csv")
    page.get_by_role("button", name="Validate mapping").click()
    expect(page.locator("#skip-invalid-label")).to_be_visible()
    expect(page.locator("#evaluate-button")).to_be_disabled()
    page.locator("#skip-invalid").check()
    expect(page.locator("#evaluate-button")).to_be_enabled()
    page.get_by_role("button", name="Run dataset test").click()
    expect(page.locator("#dataset-results")).to_be_visible()
    expect(page.locator("#dataset-message")).to_contain_text("3 records predicted; 1 rejected")

    workbook = io.BytesIO()
    pd.read_csv(io.BytesIO(source)).to_excel(workbook, index=False)
    page.locator("#dataset-file").set_input_files({"name": "SIMULATED-excel.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": workbook.getvalue()})
    page.get_by_role("button", name="Upload & inspect").click()
    expect(page.locator("#dataset-sheet")).to_contain_text("First worksheet: Sheet1")
    page.get_by_role("button", name="Validate mapping").click()
    expect(page.locator("#evaluate-button")).to_be_enabled()

    # Exercise real recovery UI while a request fails; a failed attempt must not reveal stale output.
    page.route("**/api/datasets/*/evaluate", lambda route: route.abort())
    page.get_by_role("button", name="Run dataset test").click()
    expect(page.locator("#dataset-message")).to_contain_text("Cannot reach")
    expect(page.locator("#dataset-results")).to_be_hidden()
    page.unroute("**/api/datasets/*/evaluate")
    # The deliberately aborted fetch produces a browser console resource message.
    errors = [error for error in errors if "ERR_FAILED" not in error]

    # Keyboard actions are immediate; a quick sequence of pointer navigations must settle cleanly.
    calls_before_keyboard = page.evaluate("window.__motionCalls.length")
    page.get_by_role("link", name="Predict", exact=True).focus()
    page.keyboard.press("Enter")
    expect(page.locator("#view-predict")).to_be_visible()
    page.get_by_role("button", name="Run predictions", exact=True).focus()
    page.keyboard.press("Enter")
    expect(page.locator("#prediction-output")).to_be_visible()
    assert page.evaluate("window.__motionCalls.length") == calls_before_keyboard
    page.get_by_role("link", name="Compare designs", exact=True).click()
    page.evaluate("async () => { for (const view of ['study', 'datasets', 'predict', 'datasets']) { location.hash = view; await new Promise(resolve => setTimeout(resolve, 20)); } }")
    page.evaluate("async () => await Promise.allSettled(document.getAnimations().map(animation => animation.finished))")
    expect(page.locator("#view-datasets")).to_be_visible()
    assert page.evaluate("getComputedStyle(document.querySelector('#view-datasets')).opacity") == "1"

    accessibility = []
    if AXE and AXE.is_file():
        page.evaluate(AXE.read_text())
        for view in ["predict", "compare", "study", "datasets"]:
            page.evaluate("view => location.hash = view", view)
            page.wait_for_load_state("networkidle")
            result = page.evaluate("async () => await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] } })")
            accessibility.append({"view": view, "violations": [{"id": item["id"], "impact": item["impact"], "nodes": [node["target"] for node in item["nodes"]]} for item in result["violations"]]})
    mobile = context.new_page()
    mobile.set_viewport_size({"width": 390, "height": 844})
    mobile.on("pageerror", lambda error: errors.append(str(error)))
    mobile.goto(BASE)
    mobile.wait_for_load_state("networkidle")
    for view in ["predict", "compare", "study", "datasets"]:
        mobile.evaluate("view => location.hash = view", view)
        mobile.wait_for_load_state("networkidle")
        assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Horizontal page overflow in {view}"
        mobile.screenshot(path=str(OUTPUT / f"mobile-{view}.png"), full_page=True, animations="disabled")
    mobile.goto(BASE)
    mobile.wait_for_load_state("networkidle")
    mobile.keyboard.press("Tab")
    expect(mobile.locator(".skip-link")).to_be_focused()

    reduced = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    reduced.add_init_script(MOTION_PROBE)
    reduced.route("**/*", local_only)
    reduced_page = reduced.new_page()
    reduced_page.on("pageerror", lambda error: errors.append(str(error)))
    reduced_page.goto(BASE + "/#datasets")
    reduced_page.wait_for_load_state("networkidle")
    reduced_page.get_by_role("button", name="Try simulated example", exact=True).click()
    expect(reduced_page.locator("#mapping-completeness")).to_have_text("8 of 8 mapped")
    reduced_page.get_by_role("button", name="Validate mapping").click()
    expect(reduced_page.locator("#evaluate-button")).to_be_enabled()
    reduced_page.get_by_role("button", name="Run dataset test").click()
    expect(reduced_page.locator("#dataset-results")).to_be_visible()
    assert reduced_page.evaluate("window.__motionCalls.length") == 0
    assert reduced_page.evaluate("document.getAnimations().filter(animation => animation.playState === 'running').length") == 0
    reduced.close()
    assert not errors, errors
    assert not external_requests, external_requests
    assert not any(item["violations"] for item in accessibility), accessibility
    summary = {"status": "passed", "checks": ["live prediction", "model comparison", "paper parity", "CSV import", "XLSX import", "column mapping", "prediction-only mode", "reference metrics", "residual plots", "CSV/JSON exports", "saved import reopening", "invalid-row opt-in", "request-failure recovery", "four mobile views", "keyboard entry", "no external browser requests"], "external_requests": external_requests, "page_errors": errors}
    summary["accessibility"] = accessibility or "Automated axe scan not requested; keyboard entry checked."
    summary["ui_refresh"] = {"motion_properties": ["opacity", "transform"], "reveal_duration_ms": 200, "one_click_example": "passed", "drag_and_drop": "passed", "progress_steps": "passed", "saved_mapping_choices": "passed", "keyboard_motion": "none", "reduced_motion": "none", "rapid_navigation": "passed"}
    (OUTPUT / "browser-check.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))
    context.close()
    browser.close()
