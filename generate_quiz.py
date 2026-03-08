"""
generate_quiz.py — 3단계 퀴즈 생성
─────────────────────────────────────
1단계: 네이버 뉴스 API → 오늘 경제 뉴스 검색 (실제 URL 보장)
2단계: Gemini API     → 뉴스 중 5개 선정 + 요약
3단계: Claude API     → 뉴스 기반 퀴즈 5개 + 해설 생성

환경변수:
  ANTHROPIC_API_KEY   = sk-ant-...
  GEMINI_API_KEY      = AIza...
  NAVER_CLIENT_ID     = 네이버 앱 Client ID
  NAVER_CLIENT_SECRET = 네이버 앱 Client Secret
"""

import anthropic
import json
import re
import os
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')
today_display = datetime.now(KST).strftime('%Y.%m.%d')

# 허용 언론사 목록
ALLOWED_SOURCES = [
    '조선일보', '중앙일보', '동아일보', '한겨레', '서울신문', '한국일보', '세계일보',
    '매일경제', '한국경제', '서울경제', '뉴스토마토',
    '연합뉴스', '연합인포맥스',
    'The Economist', 'Financial Times', 'New York Times', 'The Guardian',
    'Reuters', 'Bloomberg'
]

# ═══════════════════════════════════════
# 1단계: 네이버 뉴스 API → 경제 뉴스 검색
# ═══════════════════════════════════════
def fetch_news_from_naver():
    client_id     = os.environ.get('NAVER_CLIENT_ID')
    client_secret = os.environ.get('NAVER_CLIENT_SECRET')
    if not client_id or not client_secret:
        raise EnvironmentError("NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET 없음")

    print("📰 [1단계] 네이버 뉴스 API로 경제 뉴스 검색 중...")

    # 경제 키워드로 복수 검색해서 풍부한 후보 확보
    keywords = ['경제 금리 환율', '주가 코스피', '물가 수출 무역']
    candidates = []

    for kw in keywords:
        query = urllib.parse.quote(kw)
        api_url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=10&sort=date"
        req = urllib.request.Request(api_url, headers={
            'X-Naver-Client-Id':     client_id,
            'X-Naver-Client-Secret': client_secret,
        })
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read().decode())

        for item in data.get('items', []):
            # 네이버 뉴스 링크(n.news.naver.com) 대신 originallink 사용
            url = item.get('originallink') or item.get('link', '')
            title = re.sub(r'<[^>]+>', '', item.get('title', ''))
            desc  = re.sub(r'<[^>]+>', '', item.get('description', ''))
            source = item.get('source', '')

            # 허용 언론사 필터 (source 필드가 없으면 URL 도메인으로 판단)
            allowed = any(s in source for s in ALLOWED_SOURCES) or any(
                d in url for d in [
                    'chosun.com', 'joongang.co.kr', 'donga.com', 'hani.co.kr',
                    'seoul.co.kr', 'hankookilbo.com', 'segye.com',
                    'mk.co.kr', 'hankyung.com', 'sedaily.com', 'newstomato.com',
                    'yna.co.kr', 'yonhapinfomax.co.kr',
                    'economist.com', 'ft.com', 'nytimes.com',
                    'theguardian.com', 'reuters.com', 'bloomberg.com'
                ]
            )
            if not allowed:
                continue

            # n.news.naver.com URL 제외 (리다이렉트 주소)
            if 'n.news.naver.com' in url or 'news.naver.com' in url:
                if item.get('originallink'):
                    url = item['originallink']
                else:
                    continue

            if url and url.startswith('http'):
                candidates.append({
                    'title':   title,
                    'desc':    desc,
                    'url':     url,
                    'source':  source or '언론사',
                })

    # 중복 URL 제거
    seen, unique = set(), []
    for c in candidates:
        if c['url'] not in seen:
            seen.add(c['url'])
            unique.append(c)

    print(f"  ✅ 후보 뉴스 {len(unique)}개 수집")
    return unique


# ═══════════════════════════════════════
# 2단계: Gemini → 후보 중 5개 선정 + 요약
# ═══════════════════════════════════════
def select_news_with_gemini(candidates):
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY 없음")

    print("\n🔍 [2단계] Gemini로 오늘의 핵심 뉴스 5개 선정 중...")

    # 후보 목록 텍스트화
    cand_text = ""
    for i, c in enumerate(candidates[:30], 1):  # 최대 30개만 전달
        cand_text += f"{i}. [{c['source']}] {c['title']}\n   URL: {c['url']}\n   요약: {c['desc']}\n\n"

    prompt = f"""
아래는 오늘({today_display}) 네이버 뉴스에서 수집한 경제 뉴스 목록이에요.
이 중에서 가장 화제성 있고 생활과 연결된 뉴스 5개를 골라주세요.

[선정 기준]
- 일반인이 "어, 나도 들어봤는데!" 할 만큼 화제성 있는 것
- 금리·환율·주가·무역·기업 실적·물가 등 생활과 연결된 것
- 중복 주제 피하고 다양한 분야에서 선정
- 구체적인 수치가 포함된 뉴스 우선

[후보 뉴스 목록]
{cand_text}

[중요] 선정한 뉴스의 URL은 위 목록에 있는 것 그대로 복사할 것. 절대 수정하거나 새로 만들지 말 것.

각 뉴스에 대해 3~5문장 분량의 상세 요약을 작성해줘 (구체적 수치 포함).

[출력] JSON만, 다른 텍스트 없이:
{{
  "news": [
    {{
      "title": "기사 제목",
      "summary": "상세 요약 (수치 포함, 3~5문장)",
      "url": "위 목록에서 복사한 URL 그대로",
      "source": "언론사명"
    }}
  ]
}}
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4000}
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")

    with urllib.request.urlopen(req) as res:
        data = json.loads(res.read().decode())

    candidate = data["candidates"][0]
    print(f"  finishReason: {candidate.get('finishReason', 'unknown')}")
    if "content" not in candidate:
        raise ValueError("Gemini content 없음")

    raw = ""
    for part in candidate["content"]["parts"]:
        if "text" in part:
            raw += part["text"]

    print(f"  Gemini 응답 길이: {len(raw)}자")

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

    news_list = news_data.get("news", [])[:5]

    # URL이 후보 목록에 있는 것인지 검증 + 없으면 후보에서 매칭
    candidate_urls = {c['url'] for c in candidates}
    for n in news_list:
        if n.get('url') not in candidate_urls:
            # 제목으로 후보에서 찾기
            for c in candidates:
                if c['title'][:10] in n['title'] or n['title'][:10] in c['title']:
                    n['url'] = c['url']
                    break
            else:
                n['url'] = None  # 매칭 실패시 null

    print(f"  ✅ 뉴스 {len(news_list)}개 선정 완료:")
    for i, n in enumerate(news_list, 1):
        print(f"    {i}. {n['title']}")
        print(f"       🔗 {n.get('url') or '링크 없음'}")

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
        raise EnvironmentError("GEMINI_API_KEY 없음")
    if not os.environ.get('NAVER_CLIENT_ID'):
        raise EnvironmentError("NAVER_CLIENT_ID 없음")
    if not os.environ.get('NAVER_CLIENT_SECRET'):
        raise EnvironmentError("NAVER_CLIENT_SECRET 없음")

    # 1단계: 네이버로 뉴스 후보 수집
    candidates = fetch_news_from_naver()

    # 2단계: Gemini로 5개 선정 + 요약
    news_list = select_news_with_gemini(candidates)

    # 3단계: Claude로 퀴즈 생성
    quiz_data = fetch_quiz_from_claude(news_list)

    # 저장
    save(quiz_data)
    print("\n🎉 완료!")
