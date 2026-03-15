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

    # 경제 키워드 — 난이도당 7개 × 5난이도 = 35개 문제를 위해 폭넓게 수집
    keywords = [
        '경제 금리 환율', '주가 코스피 증시',
        '물가 수출 무역', '기업 실적 산업',
        '부동산 소비 고용', '한국은행 재정 정책',
        '반도체 배터리 수출', '원달러 채권 금융',
        '글로벌 경기 침체', 'GDP 성장률 경제지표',
        '미국 연준 금리', '중국 경제 무역'
    ]
    candidates = []

    for kw in keywords:
        query = urllib.parse.quote(kw)
        api_url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=20&sort=date"
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

    print("\n🔍 [2단계] Gemini로 오늘의 핵심 뉴스 35개 선정 중...")

    # 후보 목록 텍스트화 — 최대 60개 전달
    cand_text = ""
    for i, c in enumerate(candidates[:60], 1):
        cand_text += f"{i}. [{c['source']}] {c['title']}\n   URL: {c['url']}\n   요약: {c['desc']}\n\n"

    prompt = f"""
아래는 오늘({today_display}) 네이버 뉴스에서 수집한 경제 뉴스 목록이에요.
이 중에서 가장 화제성 있고 생활과 연결된 뉴스 35개를 골라주세요.
난이도별(입문/초급/중급/고급/최고급) 퀴즈를 각 7개씩 만들 수 있도록,
다양한 분야와 주제의 뉴스를 골고루 선정해주세요.

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
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8000}
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

    news_list = news_data.get("news", [])[:35]

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
아래 제공된 뉴스들을 활용해서 난이도별로 퀴즈를 7개씩, 총 35개를 만들어주세요.

[오늘의 뉴스]
{news_block}

━━━━━━━━━━━━━━━━━━━━━━
★ 사실 정확성 규칙 (절대 원칙)
━━━━━━━━━━━━━━━━━━━━━━
- 정답은 반드시 위 뉴스 원문에 명시된 수치/단어와 정확히 일치해야 함
- 수치 문제는 뉴스에 숫자가 명확히 적혀 있을 때만 출제할 것
- 뉴스에 없는 수치는 절대 정답이나 오답에 사용 금지
- 확신이 없으면 수치 문제 대신 개념·이유·영향 문제로 대체할 것
- 숫자/수치를 묻는 문제는 각 난이도에서 최대 3개까지만 허용

━━━━━━━━━━━━━━━━━━━━━━
★ 표현 중립성 규칙 (필수 준수)
━━━━━━━━━━━━━━━━━━━━━━
- 정치적·사회적 논란을 유발할 수 있는 단정적 표현은 반드시 쿠션 단어를 사용할 것
- 쿠션 단어 예시: "기사에 따르면", "~로 보도됐습니다", "전문가들은 ~로 분석합니다",
  "일각에서는 ~라는 시각도 있어요", "연구에 따르면", "해당 보도에 의하면"
- 특히 아래 표현은 반드시 쿠션 단어와 함께 사용할 것:
  · 경제 위기/침체/부실 관련 표현
  · 특정 정부/정책의 성공·실패 판단
  · 국가 간 비교 우열 표현
  · "기초체력이 약하다", "심각하다" 등 단정적 평가
- 중립적이고 사실 전달 중심의 문체를 유지할 것

━━━━━━━━━━━━━━━━━━━━━━
★ 난이도별 출제 지침 (각 7개씩)
━━━━━━━━━━━━━━━━━━━━━━

[입문 🌱 (lv-easy) — 7개]
- 기사에 등장하는 핵심 경제 용어/개념을 아는지 묻는 단답형
- 보기에 유머러스한 오답 1~2개 포함

[초급 🔥 (lv-mid) — 7개]
- 기사의 주요 사실 관계 확인
- 쉽고 명확한 보기 구성

[중급 ⚡ (lv-hard) — 7개]
- 영향·결과 예측, 수혜자/피해자 분석

[고급 💎 (lv-expert) — 7개]
- 경제 메커니즘, 원인 추론

[최고급 👑 (lv-master) — 7개]
- 내재된 경제 이론, 중장기 전망, 변수 간 연결고리 추론

━━━━━━━━━━━━━━━━━━━━━━
★ 질문 유형 규칙
━━━━━━━━━━━━━━━━━━━━━━
- 수치 문제는 각 난이도에서 최대 3개
- 나머지는 창의적 유형 (비유, 예측, 이해관계 분석, 개념 적용)

[context 필드] 2문장, "~이에요" "~해요" 친근한 말투, 정답/오답 수치 절대 미포함

[q 필드] 30자 이내

[opts 필드] 정답: 뉴스 원문과 일치 / 오답: 그럴듯하지만 뉴스에 없는 값

[exp 필드] 3문장 이내, "~해요" "~이에요" 말투, 핵심 키워드 <strong> 강조

[expert_detail 필드] 모든 문제 필수
- <span class="expert-label">🎓 박사의 한마디</span> 로 시작
- <p> 3개 문단 (이론 + 역사적 사례 + takeaway)
- 문단3: <p class="takeaway"> 핵심 한 줄 정리
- 350~450자, "~해요" "~이에요" "~거든요" 고루 혼용

[출력] JSON만, 다른 텍스트 없이:
{{
  "date": "{today}",
  "quizzes": {{
    "lv-easy":   [ 7개의 퀴즈 객체 ],
    "lv-mid":    [ 7개의 퀴즈 객체 ],
    "lv-hard":   [ 7개의 퀴즈 객체 ],
    "lv-expert": [ 7개의 퀴즈 객체 ],
    "lv-master": [ 7개의 퀴즈 객체 ]
  }}
}}

각 퀴즈 객체 형식:
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
"""


def fetch_quiz_from_claude(news_list):
    import random
    client = anthropic.Anthropic()
    print("\n🤖 [3단계] Claude로 퀴즈 생성 중... (난이도별 7개씩)")

    prompt = build_quiz_prompt(news_list)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16000,
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

    # quizzes가 dict(난이도별) 구조인지 확인
    quizzes_raw = data.get('quizzes', {})
    levels = ['lv-easy','lv-mid','lv-hard','lv-expert','lv-master']

    # 난이도별로 정답 랜덤 셔플 + URL 주입
    for lv_idx, lv in enumerate(levels):
        pool = quizzes_raw.get(lv, [])
        # 뉴스를 난이도별로 나눠서 URL 매핑 (35개 뉴스를 5구간으로 분할)
        seg_size = max(1, len(news_list) // 5)
        seg_news = news_list[lv_idx * seg_size : (lv_idx + 1) * seg_size]

        for q_idx, q in enumerate(pool):
            # URL 주입
            news = seg_news[q_idx % len(seg_news)] if seg_news else {}
            q['article_title'] = news.get('title', '')
            q['article_url']   = news.get('url', '')

            # 정답 랜덤 셔플
            opts = q.get('opts', [])
            ans  = q.get('ans', 0)
            if not (0 <= ans <= len(opts) - 1): ans = 0
            correct = opts[ans]
            others  = [o for j, o in enumerate(opts) if j != ans]
            random.shuffle(others)
            new_pos = random.randint(0, 3)
            others.insert(new_pos, correct)
            q['opts'] = others
            q['ans']  = new_pos

        print(f"  {lv}: {len(pool)}개")

    data['quizzes'] = quizzes_raw
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
