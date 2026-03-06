"""
경제 퀴즈 자동 생성 스크립트
-------------------------------
사용법:
  1. pip install anthropic
  2. 환경변수 설정: export ANTHROPIC_API_KEY="sk-..."
  3. 실행: python generate_quiz.py

결과물: quiz_YYYYMMDD.json 파일이 생성됩니다.
이 파일을 GitHub에 올리면 앱에 자동 반영됩니다.
"""

import anthropic
import json
import re
from datetime import datetime

# ───────────────────────────────────────────
# 1. 오늘의 뉴스 (여기만 매일 교체하면 됩니다)
# ───────────────────────────────────────────
TODAY_NEWS = """
[2026년 3월 첫째 주 주요 경제 뉴스]

1. 호르무즈 해협 봉쇄 위기
   - 이란이 호르무즈 해협을 통한 석유 수출 차단 선언
   - 전 세계 원유 수송량의 20%가 이 해협을 통과함
   - 브렌트유 배럴당 85달러 돌파, 13% 이상 급등

2. 국내 증시·환율 패닉
   - 코스피 하루 만에 433포인트(7.49%) 폭락, 5358로 마감
   - 원·달러 환율 1500원 돌파 (금융위기 이후 처음)
   - 코스닥 사이드카 발동 (7.83% 급락)

3. 금값 사상 최고치
   - 현물 금 가격 온스당 5,376달러 기록
   - 지정학적 위기 때마다 금이 오르는 이유: 안전자산 선호

4. 한국은행 기준금리 2.5% 동결 (2월 26일)
   - 물가 안정세 + 성장 회복세 감안해 동결 결정
   - 추가 인하 여부는 중동 상황에 달림

5. 중국 제조업 PMI 49 → 2개월 연속 위축
   - PMI 50 이하 = 경기 수축 신호
   - 내수 부진 + 수출 불확실성 겹쳐
"""

# ───────────────────────────────────────────
# 2. 프롬프트 (검증된 퀴즈 생성 프롬프트)
# ───────────────────────────────────────────
QUIZ_PROMPT = f"""
아래 최신 경제 뉴스를 읽고, 퀴즈 8개를 JSON 형식으로 만들어줘.

[오늘의 뉴스]
{TODAY_NEWS}

[난이도 구성]
- 입문 (lv-easy): 2개 — "얼마?" "누가?" 같은 단순 사실 확인
- 초급 (lv-mid): 2개 — "왜 이런 일이?" 원인 묻기
- 중급 (lv-hard): 2개 — 결과나 영향 묻기
- 고급 (lv-expert): 1개 — 경제 메커니즘 묻기
- 최고급 (lv-master): 1개 — 여러 개념을 연결해서 추론하기

[질문 작성 규칙]
- 15자 이내로 짧고 명확하게
- "얼마?" / "왜?" / "아닌 것은?" 세 패턴 중 하나 사용
- 4지선다, 정답 1개
- 오답 3개는 그럴듯하게

[해설 작성 규칙]
- 2문장 이내, 핵심 키워드 1개만 **굵게**
- 생활 속 비유 1개 포함
- "~해요" 말투

[고급·최고급 추가 해설 (detail 필드)]
- 경제학 용어로 메커니즘 설명 (전문 용어 + 쉬운 설명 병행)
- HTML 형식, <p> 태그 사용
- 마지막 문단은 class="detail-takeaway" 붙여서 핵심 한 줄 정리

[출력 형식] — 반드시 아래 JSON 구조만 출력, 다른 말 없이

{{
  "date": "{datetime.now().strftime('%Y-%m-%d')}",
  "quizzes": [
    {{
      "levelClass": "lv-easy",
      "source": "날짜 · 출처",
      "q": "질문",
      "opts": ["①", "②", "③", "④"],
      "ans": 정답인덱스(0~3),
      "exp": "한 줄 해설 (HTML 가능)",
      "detail": null
    }}
  ]
}}

고급(lv-expert), 최고급(lv-master) 문제만 detail 필드에 HTML 넣고,
나머지는 null로 두어줘.
"""

# ───────────────────────────────────────────
# 3. Claude API 호출
# ───────────────────────────────────────────
def generate_quiz():
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 자동 사용

    print("🤖 Claude에게 퀴즈 생성 요청 중...")

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[
            {"role": "user", "content": QUIZ_PROMPT}
        ]
    )

    raw = message.content[0].text

    # JSON 부분만 추출 (혹시 앞뒤에 텍스트 있을 경우 대비)
    match = re.search(r'\{[\s\S]*\}', raw)
    if not match:
        raise ValueError("JSON을 찾을 수 없어요. Claude 응답:\n" + raw)

    quiz_data = json.loads(match.group())
    return quiz_data


# ───────────────────────────────────────────
# 4. 파일 저장
# ───────────────────────────────────────────
def save_quiz(quiz_data):
    today = datetime.now().strftime("%Y%m%d")
    filename = f"quiz_{today}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 저장 완료: {filename}")
    print(f"📊 퀴즈 {len(quiz_data['quizzes'])}개 생성됨")

    # 미리보기
    for i, q in enumerate(quiz_data["quizzes"]):
        level_map = {
            "lv-easy": "🌱 입문",
            "lv-mid": "🔥 초급",
            "lv-hard": "⚡ 중급",
            "lv-expert": "💎 고급",
            "lv-master": "👑 최고급"
        }
        level = level_map.get(q["levelClass"], q["levelClass"])
        print(f"  {i+1}. [{level}] {q['q']}")

    return filename


# ───────────────────────────────────────────
# 5. 실행
# ───────────────────────────────────────────
if __name__ == "__main__":
    quiz_data = generate_quiz()
    filename = save_quiz(quiz_data)

    print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎉 완료! 다음 단계:
   1. {filename} 파일을 GitHub에 업로드
   2. index.html에서 이 JSON을 불러오도록 연결
   (자동 연결은 index.html 상단 fetch 코드 참고)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
