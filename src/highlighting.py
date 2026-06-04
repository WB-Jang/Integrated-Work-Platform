import json
import re

def highlight_errors(original_text, analysis_result_json):
    """
    원본 텍스트에서 error_sentence를 찾아 빨간색 배경 처리를 합니다.
    """
    highlighted_text = original_text

    try:
        # 1. JSON 전처리
        clean_json = analysis_result_json.replace("```json", "").replace("```", "").strip()
        errors = json.loads(clean_json)

        if not isinstance(errors, list):
            return original_text, []

        for error in errors:
            target = error.get("error_sentence", "").strip()

            if not target:
                continue

            # 2. 단순 replace 시도
            if target in highlighted_text:
                replacement = f"<span style='background-color: #ffdce0; color: #d8000c; font-weight: bold; padding: 2px 4px; border-radius: 4px;'>{target}</span>"
                highlighted_text = highlighted_text.replace(target, replacement)

            # 3. [보완] 단순 매칭 실패 시, 공백/줄바꿈을 유연하게 처리하여 검색
            else:
                # target의 특수문자를 이스케이프하고, 공백을 유연한 정규식 패턴(\s+)으로 변경
                # 예: "안녕 하세요" -> "안녕\s+하세요" (줄바꿈이나 여러 공백도 매칭됨)
                import re
                escaped_target = re.escape(target)
                pattern = escaped_target.replace(r"\ ", r"\s+")

                # HTML 태그로 감싸기 위한 정규식 치환
                replacement = f"<span style='background-color: #ffdce0; color: #d8000c; font-weight: bold; padding: 2px 4px; border-radius: 4px;'>\g<0></span>"

                # 원본 텍스트가 이미 HTML 태그 등으로 오염되지 않았다고 가정하고 수행
                highlighted_text = re.sub(pattern, replacement, highlighted_text)

        return highlighted_text, errors

    except json.JSONDecodeError:
        return original_text, []
    except Exception:
        return original_text, []
