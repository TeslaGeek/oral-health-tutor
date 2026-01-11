def build_test_results(case_payload: dict, selected_tests: list, *, audience: str = "student"):
    """
    Build test results for either student UI (no gold leak) or marker view (includes truth).
    """
    case_payload = case_payload or {}
    catalogue = case_payload.get("tests_catalogue", {}) or {}
    test_options = catalogue.get("options", []) or []
    availability = catalogue.get("availability", {}) or {}

    tests_by_code = {t.get("code"): t for t in test_options}
    selected = selected_tests or []

    test_results = []
    for code in selected:
        meta = tests_by_code.get(code, {}) or {}
        test_type = meta.get("type")
        avail = availability.get(code, {}) or {}

        available_flag = bool(avail.get("available"))
        image_url = avail.get("image_url")

        if audience == "student":
            result_text = None
            result_html = None
            if test_type == "radiograph":
                key_findings = []
                if available_flag:
                    if image_url:
                        result_text = "Radiograph image available below. Please write your radiograph report."
                    else:
                        result_text = "Radiograph available. Please write your radiograph report."
                else:
                    result_text = avail.get("reason") or "Radiograph not available for this case."
            else:
                key_findings = avail.get("key_findings") or []
                if available_flag:
                    if code == "BPE" and key_findings:
                        upper_codes = []
                        lower_codes = []
                        for line in key_findings:
                            if not isinstance(line, str):
                                continue
                            if line.lower().startswith("upper"):
                                upper_codes = line.split(":", 1)[-1].strip().split()
                            elif line.lower().startswith("lower"):
                                lower_codes = line.split(":", 1)[-1].strip().split()

                        def bpe_row(label: str, codes: list) -> str:
                            cells = "".join(
                                f"<div class='bpe-cell'>{code}</div>" for code in codes
                            )
                            return (
                                "<div class='bpe-row'>"
                                f"<div class='bpe-label'>{label}</div>"
                                f"<div class='bpe-grid'>{cells}</div>"
                                "</div>"
                            )

                        result_html = (
                            "<div class='bpe-wrapper mt-2'>"
                            f"{bpe_row('Upper', upper_codes)}"
                            f"{bpe_row('Lower', lower_codes)}"
                            "</div>"
                        )
                    elif not key_findings:
                        result_text = "Results available for this test."
                else:
                    result_text = avail.get("reason") or "Results not available for this test."

            test_results.append(
                {
                    "code": code,
                    "name": meta.get("name", code),
                    "type": test_type,
                    "available": available_flag,
                    "result_text": result_text,
                    "result_html": result_html,
                    "image_url": image_url,
                    "key_findings": key_findings,
                }
            )
            continue

        # Marker view (includes truth)
        report_lines = avail.get("gold_report") or avail.get("key_findings")
        if available_flag and report_lines:
            marker_text = "; ".join(report_lines)
        elif available_flag:
            marker_text = "Results available for this test."
        else:
            marker_text = avail.get("reason") or "Results not available for this test."

        test_results.append(
            {
                "code": code,
                "name": meta.get("name", code),
                "type": test_type,
                "available": available_flag,
                "result_text": marker_text,
                "image_url": image_url,
                "gold_report": avail.get("gold_report"),
                "key_findings": avail.get("key_findings"),
            }
        )

    return test_options, test_results
