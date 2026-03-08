"""
generate_quiz.py — 2단계 퀴즈 생성
─────────────────────────────────────
1단계: Gemini API (무료) → 오늘 경제 뉴스 5개 + 링크 수집
2단계: Claude API       → 뉴스 기반 퀴즈 5개 + 해설 생성

환경변수:
  ANTHROPIC_API_KEY = sk-ant-...
  GEMINI_API_KEY    = AIza...
"""

import anthropic
import json
import re
import os
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')
today_display = datetime.now(KST).strftime('%Y.%m.%d')

# ═══════════════════════════════════════
# 1단계: Gemini → 오늘 뉴스 5개 수집
# ═══════════════════════════════════════
GEMINI_NEWS_PROMPT = f"""
오늘({today_display}) 기준으로 가장 화제가 된 한국 경제 뉴스 5가지를 찾아줘.

[선정 기준]
- 일반인이 "어, 나도 들어봤는데!" 할 만큼 화제성 있는 것
- 금리·환율·주가·무역·기업 실적·물가 등 생활과 연결된 것
- 숫자/금액/퍼센트가 등장하는 구체적인 뉴스

[허용 출처] 아래 목록에 있는 언론사 기사만 사용할 것
국내 일간지: 조선일보, 중앙일보, 동아일보, 한겨레, 서울신문, 한국일보, 세계일보
국내 경제지: 매일경제, 한국경제, 서울경제, 뉴스토마토
국내 통신사: 연합뉴스, 연합인포맥스
외신: The Economist, Financial Times, New York Times, The Guardian, Reuters, Bloomberg
위 목록에 없는 출처(네이버뉴스, 다음뉴스, 유튜브, 블로그, 커뮤니티 등)는 절대 사용 금지

[URL 규칙] ★ 매우 중요
- Google Search로 직접 검색해서 실제로 접속 가능한 URL만 사용할 것
- 검색 결과에서 해당 기사를 직접 확인한 URL만 넣을 것
- URL을 추측하거나 임의로 만들지 말 것
- 확인되지 않은 URL이면 url 필드를 null로 설정
- 연합뉴스 URL 형식 예시: https://www.yna.co.kr/view/AKR20260308XXXXXXX
- 한국경제 URL 형식 예시: https://www.hankyung.com/article/XXXXXXXXXX
- 조선일보 URL 형식 예시: https://www.chosun.com/economy/XXXX/XX/XX/XXXXXXXXXX/

[각 뉴스 항목에 포함할 것]
1. 제목
2. 핵심 내용 요약 (3~5문장, 구체적 수치 반드시 포함)
3. 실제 확인된 기사 URL (확인 불가시 null)
4. 출처 언론사명

[출력] JSON만, 다른 텍스트 없이:
{{
  "news": [
    {{
      "title": "기사 제목",
      "summary": "핵심 내용 요약 (수치 포함, 3~5문장)",
      "url": "https://실제확인된URL 또는 null",
      "source": "연합뉴스"
    }}
  ]
}}
"""

def fetch_news_from_gemini():
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY 없음")

    print("📰 [1단계] Gemini로 오늘의 뉴스 수집 중...")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": GEMINI_NEWS_PROMPT}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4000}
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as res:
        data = json.loads(res.read().decode())

    # 응답 구조 디버그 출력
    candidate = data["candidates"][0]
    print(f"  finishReason: {candidate.get('finishReason', 'unknown')}")
    if "content" not in candidate:
        print(f"  ⚠️ content 없음. candidate 키: {list(candidate.keys())}")
        print(f"  전체 응답: {json.dumps(data, ensure_ascii=False)[:500]}")
        raise ValueError("Gemini content 없음 — finishReason 확인 필요")

    # 검색 결과가 포함된 응답에서 텍스트만 추출
    raw = ""
    for part in data["candidates"][0]["content"]["parts"]:
        if "text" in part:
            raw += part["text"]

    print(f"  Gemini 응답 길이: {len(raw)}자")

    # JSON 블록 정확히 추출 (중첩 중괄호 처리)
    start = raw.find('{')
    if start == -1:
        raise ValueError("Gemini JSON { 없음:\n" + raw[:300])

    depth, end = 0, -1
    for i, ch in enumerate(raw[start:], start):
        if ch == '{': depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        raise ValueError("Gemini JSON } 없음:\n" + raw[:300])

    try:
        news_data = json.loads(raw[start:end])
    except json.JSONDecodeError:
        cleaned = raw[start:end].replace('\n', ' ').replace('\r', '')
        news_data = json.loads(cleaned)
    news_list = news_data.get("news", [])

    print(f"  ✅ 뉴스 {len(news_list)}개 수집 완료:")
    for i, n in enumerate(news_list, 1):
        print(f"    {i}. {n['title']}")
        print(f"       🔗 {n.get('url', 'URL 없음')}")

    return news_list


# ═══════════════════════════════════════
# 2단계: Claude → 뉴스 기반 퀴즈 생성
# ═══════════════════════════════════════
def build_quiz_prompt(news_list):
    news_block = ""
    for i, n in enumerate(news_list, 1):
        news_block += f"""
[뉴스 {i}] {n['title']}
출처: {n['source']} | URL: {n.get('url', '')}
내용: {n['summary']}
"""

    return f"""
당신은 경제 퀴즈 출제 전문가입니다.
아래 제공된 뉴스 5개를 각각 하나씩 사용해서 퀴즈 5개를 만들어주세요.

[오늘의 뉴스]
{news_block}

━━━━━━━━━━━━━━━━━━━━━━
★ 사실 정확성 규칙 (절대 원칙)
━━━━━━━━━━━━━━━━━━━━━━
- 정답은 반드시 위 뉴스 원문에 명시된 수치/단어와 글자 하나까지 정확히 일치해야 함
- 수치 문제는 뉴스에 숫자가 명확히 적혀 있을 때만 출제할 것
- 뉴스에 없는 수치는 절대 정답이나 오답에 사용 금지
- 확신이 없으면 수치 문제 대신 개념·이유·영향 문제로 대체할 것
- 오답도 뉴스에 없는 수치여야 하되, 정답과 비슷한 자릿수로 구성

━━━━━━━━━━━━━━━━━━━━━━
★ 질문 유형 규칙
━━━━━━━━━━━━━━━━━━━━━━
- 숫자/수치를 묻는 문제는 5개 중 최대 3개까지만 허용
- 나머지 2개 이상은 창의적이고 재미있는 유형으로:
  예) "이 상황과 가장 비슷한 역사적 사례는?" (비유 찾기)
  예) "이 뉴스에서 가장 큰 피해자/수혜자는?" (이해관계 분석)
  예) "~가 계속된다면 6개월 후 어떤 일이?" (예측)
  예) "경제학자라면 이 원인을 뭐라고 설명할까?" (개념 적용)
- 창의적 유형 보기는 문장형으로 작성

[난이도 구성] 뉴스 순서대로 1개씩
1번 뉴스 → 입문 (lv-easy)    — 핵심 사실 확인
2번 뉴스 → 초급 (lv-mid)     — 원인·배경 추론
3번 뉴스 → 중급 (lv-hard)    — 영향·결과 예측
4번 뉴스 → 고급 (lv-expert)  — 경제 메커니즘
5번 뉴스 → 최고급 (lv-master) — 개념 연결 추론

[context 필드 — 배경 설명]
- 2문장, 친근한 말투 ("~했어요" "~거든요")
- ★ 절대 금지: 정답/오답 수치나 핵심 단어를 context에 직접 쓰지 말 것

[q 필드] 30자 이내

[opts 필드]
- 정답: 뉴스 원문과 정확히 일치
- 오답 3개: 그럴듯하지만 뉴스에 없는 값

[exp 필드] 3문장 이내, "~해요" 말투, 핵심 키워드 <strong> 강조

[expert_detail 필드] 모든 문제 필수
- <span class="expert-label">🎓 박사의 한마디</span> 로 시작
- <p> 3개 문단 (이론 + 역사적 사례 + takeaway)
- 문단3: <p class="takeaway"> 핵심 한 줄 정리
- 350~450자, "~해요" "~거든요" 말투

[출력] JSON만, 다른 텍스트 없이:
{{
  "date": "{today}",
  "quizzes": [
    {{
      "levelClass": "lv-easy",
      "source": "{today_display} · 출처명",
      "context": "2문장 배경 설명",
      "q": "질문 (30자 이내)",
      "opts": ["보기1", "보기2", "보기3", "보기4"],
      "ans": 0,
      "exp": "한 줄 해설 HTML",
      "expert_detail": "전문가 해설 HTML"
    }}
  ]
}}
"""


def fetch_quiz_from_claude(news_list):
    import random
    client = anthropic.Anthropic()
    print("\n🤖 [2단계] Claude로 퀴즈 생성 중...")

    prompt = build_quiz_prompt(news_list)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}]
    )

    texts = [b.text for b in msg.content if hasattr(b, 'text') and b.text.strip()]
    if not texts:
        raise ValueError("Claude 텍스트 응답 없음")

    raw = max(texts, key=len)
    print(f"  Claude 응답 길이: {len(raw)}자")

    start = raw.find('{')
    if start == -1:
        raise ValueError("JSON { 없음:\n" + raw[:300])

    depth, end = 0, -1
    for i, ch in enumerate(raw[start:], start):
        if ch == '{': depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        raise ValueError("JSON } 없음")

    try:
        data = json.loads(raw[start:end])
    except json.JSONDecodeError:
        cleaned = raw[start:end].replace('\n', ' ').replace('\r', '')
        data = json.loads(cleaned)

    assert len(data['quizzes']) == 5, f"퀴즈 5개 필요. 실제: {len(data['quizzes'])}개"

    # Gemini가 수집한 URL을 퀴즈에 직접 주입 + 정답 위치 랜덤 셔플
    for i, q in enumerate(data['quizzes']):
        # 뉴스 링크 주입 (Claude에게 맡기지 않고 Python에서 직접)
        news = news_list[i] if i < len(news_list) else {}
        q['article_title'] = news.get('title', '')
        q['article_url']   = news.get('url', '')

        # 정답 위치 랜덤 셔플
        opts = q.get('opts', [])
        ans  = q.get('ans', 0)
        if not (0 <= ans <= len(opts) - 1):
            ans = 0
        correct = opts[ans]
        others  = [o for j, o in enumerate(opts) if j != ans]
        random.shuffle(others)
        new_pos = random.randint(0, 3)
        others.insert(new_pos, correct)
        q['opts'] = others
        q['ans']  = new_pos

    return data


# ═══════════════════════════════════════
# 저장
# ═══════════════════════════════════════
def save(data):
    with open('quiz_today.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    levels = {'lv-easy':'🌱 입문','lv-mid':'🔥 초급','lv-hard':'⚡ 중급',
              'lv-expert':'💎 고급','lv-master':'👑 최고급'}
    print(f"\n✅ quiz_today.json 저장 완료 — 퀴즈 {len(data['quizzes'])}개")
    for i, q in enumerate(data['quizzes'], 1):
        print(f"  {i}. [{levels.get(q['levelClass'], q['levelClass'])}] {q['q']}")
        if q.get('article_url'):
            print(f"     🔗 {q['article_url']}")


# ═══════════════════════════════════════
# 실행
# ═══════════════════════════════════════
if __name__ == '__main__':
    if not os.environ.get('ANTHROPIC_API_KEY'):
        raise EnvironmentError("ANTHROPIC_API_KEY 없음")
    if not os.environ.get('GEMINI_API_KEY'):
        raise EnvironmentError("GEMINI_API_KEY 없음\nGoogle AI Studio에서 발급: https://aistudio.google.com/apikey")

    # 1단계: 뉴스 수집
    news_list = fetch_news_from_gemini()

    # 2단계: 퀴즈 생성
    quiz_data = fetch_quiz_from_claude(news_list)

    # 저장
    save(quiz_data)
    print("\n🎉 완료!")
