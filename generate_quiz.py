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

[각 뉴스 항목에 포함할 것]
1. 제목
2. 핵심 내용 요약 (3~5문장, 구체적 수치 반드시 포함)
3. 실제 기사 URL (검색해서 실제 존재하는 URL만)
4. 출처 언론사명

[출력] JSON만, 다른 텍스트 없이:
{{
  "news": [
    {{
      "title": "기사 제목",
      "summary": "핵심 내용 요약 (수치 포함, 3~5문장)",
      "url": "https://실제기사URL",
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
★ 사실 정확성 규칙 (가장 중요)
━━━━━━━━━━━━━━━━━━━━━━
- 정답과 오답은 반드시 위 뉴스에 명시된 사실에만 근거할 것
- 뉴스에 없는 수치나 사실을 절대 만들어내지 말 것
- 정답 보기는 뉴스 원문의 수치/단어와 정확히 일치해야 함

━━━━━━━━━━━━━━━━━━━━━━
★ 질문 유형 규칙
━━━━━━━━━━━━━━━━━━━━━━
- 숫자/수치를 묻는 문제는 5개 중 최대 1~2개만 허용
- 나머지 3~4개는 아래처럼 창의적이고 재미있는 유형으로:
  예) "만약 ~라면 어떻게 될까요?" (가상 시나리오)
  예) "~와 가장 비슷한 상황은?" (비유 찾기)
  예) "이 뉴스에서 가장 큰 수혜자/피해자는?" (이해관계 분석)
  예) "~의 진짜 이유로 가장 적절한 것은?" (원인 추론)
  예) "~가 계속된다면 1년 후 어떤 일이 생길까요?" (예측)
  예) "경제학자라면 이 상황을 어떻게 설명할까요?" (개념 적용)
- 보기도 단순 수치 나열 말고 문장형으로 재미있게

[난이도 구성] 뉴스 순서대로 1개씩
1번 뉴스 → 입문 (lv-easy)    — 핵심 사실 확인 (수치 가능)
2번 뉴스 → 초급 (lv-mid)     — 원인·배경 추론
3번 뉴스 → 중급 (lv-hard)    — 영향·결과 예측 (창의적 유형)
4번 뉴스 → 고급 (lv-expert)  — 경제 메커니즘 (창의적 유형)
5번 뉴스 → 최고급 (lv-master) — 개념 연결 추론 (창의적 유형)

[context 필드 — 배경 설명]
- 2문장, 친근한 말투 ("~했어요" "~거든요")
- 뉴스 내용을 독자가 모른다고 가정하고 설명
- ★ 절대 금지: 정답/오답 수치나 핵심 단어를 context에 직접 쓰지 말 것
  → 대신 "어떻게 됐을까요? 😏" 식으로 궁금증 유발

[q 필드 — 질문]
- 30자 이내, 뉴스 사실에 근거한 명확한 질문

[opts 필드 — 보기]
- 정답: 뉴스 원문 사실과 정확히 일치
- 오답 3개: 그럴듯하지만 뉴스에 없는 내용
- 창의적 유형 문제는 보기도 문장형으로

[exp 필드 — 한 줄 해설]
- 3문장 이내, "~해요" 말투
- 핵심 키워드 <strong> 강조
- 정답 근거를 뉴스 내용 기반으로 설명

[expert_detail 필드] 모든 문제 필수
- <span class="expert-label">🎓 박사의 한마디</span> 로 시작
- <p> 3개 문단
- 문단1: 관련 경제 이론 + 괄호 안에 쉬운 풀이
- 문단2: 역사적 실제 사례 (연도·수치 포함)
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
      "expert_detail": "전문가 해설 HTML",
      "article_title": "기사 제목",
      "article_url": "기사 URL"
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

    # Python에서 직접 정답 위치 랜덤 셔플 (Claude가 못 지켜도 여기서 보정)
    for q in data['quizzes']:
        opts = q['opts']
        ans  = q.get('ans', 0)

        # ans가 범위 밖이면 0으로 보정
        if not (0 <= ans <= 3):
            ans = 0

        # 정답 보기를 랜덤 위치로 이동
        correct = opts[ans]
        others  = [o for i, o in enumerate(opts) if i != ans]
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
