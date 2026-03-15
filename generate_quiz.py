"""
generate_quiz.py — 3단계 퀴즈 생성
─────────────────────────────────────
1단계: 네이버 뉴스 API → 경제 뉴스 후보 수집
2단계: Gemini          → 핵심 뉴스 15개 선정 + 요약
3단계: Claude          → 난이도별 1회씩 총 5회 호출, 각 7개 퀴즈 생성

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
import random
import unicodedata
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

KST           = timezone(timedelta(hours=9))
today         = datetime.now(KST).strftime('%Y-%m-%d')
today_display = datetime.now(KST).strftime('%Y.%m.%d')

LEVELS = ['lv-easy', 'lv-mid', 'lv-hard', 'lv-expert', 'lv-master']
LABELS = {'lv-easy':'🌱 입문','lv-mid':'🔥 초급','lv-hard':'⚡ 중급',
          'lv-expert':'💎 고급','lv-master':'👑 최고급'}

ALLOWED_DOMAINS = [
    'chosun.com','joongang.co.kr','donga.com','hani.co.kr',
    'seoul.co.kr','hankookilbo.com','segye.com',
    'mk.co.kr','hankyung.com','sedaily.com','newstomato.com',
    'yna.co.kr','yonhapinfomax.co.kr',
    'economist.com','ft.com','nytimes.com',
    'theguardian.com','reuters.com','bloomberg.com'
]

# ═══════════════════════════════════════════════
# 1단계: 네이버 뉴스 API
# ═══════════════════════════════════════════════
def fetch_news_from_naver():
    client_id     = os.environ.get('NAVER_CLIENT_ID')
    client_secret = os.environ.get('NAVER_CLIENT_SECRET')
    if not client_id or not client_secret:
        raise EnvironmentError("NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET 없음")

    print("📰 [1단계] 네이버 뉴스 API 검색 중...")
    keywords = [
        '경제 금리 환율', '주가 코스피 증시',
        '물가 수출 무역', '기업 실적 산업',
        '부동산 소비 고용', '한국은행 재정 정책',
        '반도체 배터리 수출', '원달러 채권 금융',
        '글로벌 경기', 'GDP 성장률', '미국 연준', '중국 경제'
    ]
    candidates = []
    for kw in keywords:
        query   = urllib.parse.quote(kw)
        api_url = (f"https://openapi.naver.com/v1/search/news.json"
                   f"?query={query}&display=20&sort=date")
        req = urllib.request.Request(api_url, headers={
            'X-Naver-Client-Id':     client_id,
            'X-Naver-Client-Secret': client_secret,
        })
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read().decode())
        for item in data.get('items', []):
            url    = item.get('originallink') or item.get('link', '')
            title  = re.sub(r'<[^>]+>', '', item.get('title', ''))
            desc   = re.sub(r'<[^>]+>', '', item.get('description', ''))
            source = item.get('source', '')
            if not any(d in url for d in ALLOWED_DOMAINS): continue
            if 'n.news.naver.com' in url or 'news.naver.com' in url:
                url = item.get('originallink', '')
            if not url.startswith('http'): continue
            candidates.append({'title':title,'desc':desc,'url':url,'source':source or '언론사'})

    seen, unique = set(), []
    for c in candidates:
        if c['url'] not in seen:
            seen.add(c['url']); unique.append(c)
    print(f"  ✅ 후보 {len(unique)}개 수집")
    return unique


# ═══════════════════════════════════════════════
# 2단계: Gemini → 핵심 뉴스 15개 선정
# ═══════════════════════════════════════════════
def select_news_with_gemini(candidates):
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key: raise EnvironmentError("GEMINI_API_KEY 없음")

    print("\n🔍 [2단계] Gemini로 핵심 뉴스 15개 선정 중...")
    cand_text = ""
    for i, c in enumerate(candidates[:60], 1):
        cand_text += f"{i}. [{c['source']}] {c['title']}\n   URL: {c['url']}\n   요약: {c['desc']}\n\n"

    prompt = f"""
오늘({today_display}) 네이버 뉴스에서 수집한 경제 뉴스 중 화제성·생활밀접도 높은 뉴스 15개를 골라주세요.
주제 다양성 유지, 중복 주제 금지, 수치 포함 뉴스 우선.
URL은 목록에 있는 것 그대로 복사 (변경·생성 절대 금지).
각 뉴스 3~5문장 상세 요약 (수치 필수).

[후보 목록]
{cand_text}

[출력] JSON만:
{{"news":[{{"title":"","summary":"","url":"","source":""}}]}}
"""
    url     = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"gemini-2.5-flash-lite:generateContent?key={api_key}")
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 6000}
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as res:
        data = json.loads(res.read().decode())

    candidate = data["candidates"][0]
    print(f"  finishReason: {candidate.get('finishReason','unknown')}")
    if "content" not in candidate: raise ValueError("Gemini content 없음")
    raw = "".join(p["text"] for p in candidate["content"]["parts"] if "text" in p)
    print(f"  Gemini 응답 {len(raw)}자")

    news_list = _parse_json(raw).get("news", [])[:15]

    cand_urls = {c['url'] for c in candidates}
    for n in news_list:
        if n.get('url') not in cand_urls:
            for c in candidates:
                if c['title'][:10] in n['title'] or n['title'][:10] in c['title']:
                    n['url'] = c['url']; break
            else:
                n['url'] = None

    print(f"  ✅ {len(news_list)}개 선정:")
    for i, n in enumerate(news_list, 1):
        print(f"    {i:2}. {n['title'][:45]}")
        print(f"        🔗 {n.get('url') or '링크없음'}")
    return news_list


# ═══════════════════════════════════════════════
# 3단계: Claude → 난이도별 1회씩 5회 호출
# ═══════════════════════════════════════════════
def assign_news_to_levels(news_list):
    n   = len(news_list)
    seg = max(1, n // 5)
    out = {}
    for i, lv in enumerate(LEVELS):
        s = i * seg
        e = s + seg if i < 4 else n
        out[lv] = news_list[s:e]
    return out


def build_level_prompt(lv, lv_news):
    news_block = ""
    for j, n in enumerate(lv_news, 1):
        news_block += f"[뉴스{j}] {n['title']}\n내용: {n['summary']}\n\n"

    level_guide = {
        'lv-easy':
            "★ 기사 속 핵심 경제 용어/개념을 아는지 묻는 단답형 위주.\n"
            "★ 오답 1~2개는 유머러스하게 (예: '내 월급도 같이 오른다 🙏', '아무 일도 안 생긴다').\n"
            "★ context: '오늘 뉴스에 이 개념이 나왔는데, 알고 있나요? 😊' 느낌으로.",
        'lv-mid':
            "★ 기사의 주요 사실 관계 확인.\n"
            "★ 쉽고 명확한 보기 (유머 없이).",
        'lv-hard':
            "★ 영향·결과 예측 (수혜자/피해자, 6개월 후 변화 등).\n"
            "★ 창의적 유형 가능 (이해관계 분석, 예측).",
        'lv-expert':
            "★ 경제 메커니즘, 원인 추론.\n"
            "★ 경제학 개념 적용 문제 포함.",
        'lv-master':
            "★ 기사에 내재된 경제 이론, 중장기 전망, 변수 간 연결고리.\n"
            "★ '이 상황이 지속되면?', 'A→B→C 파급 경로는?' 유형."
    }[lv]

    return f"""당신은 경제 퀴즈 출제 전문가입니다.
아래 뉴스 {len(lv_news)}개로 [{LABELS[lv]}] 난이도 퀴즈 7개를 만들어주세요.

[뉴스]
{news_block}

[출제 방향]
{level_guide}

[공통 규칙]
- 정답: 뉴스 원문 수치/단어와 정확히 일치. 뉴스에 없는 수치 절대 사용 금지.
- 수치 문제 최대 3개. 나머지는 개념·원인·영향 유형.
- 7문제 안에서 같은 뉴스 최대 2회 사용. {len(lv_news)}개 뉴스 골고루 활용.
- 단정 표현에 쿠션 단어 필수 ("기사에 따르면", "~로 보도됐습니다", "전문가들은 ~로 분석합니다").
- context: 2문장. 정답 수치 절대 미포함. 친근한 말투 ("~이에요" "~해요" 위주).
- q: 30자 이내.
- exp: 2~3문장. <strong> 핵심 키워드 강조. "~해요" "~이에요" 말투.
- expert_detail 규칙:
    · <span class="expert-label">🎓 박사의 한마디</span> 로 시작
    · <p> 태그 3개 문단 구성
    · 문단1: 관련 경제학 이론명 + <strong> 강조 + 괄호 안에 쉬운 풀이, 2~3문장
    · 문단2: 역사적 실제 사례 (연도·나라·수치 포함), 2~3문장
    · 문단3: <p class="takeaway"> 태그, 오늘 기사와 연결한 핵심 한 줄 정리
    · 전체 400~550자. "~해요" "~이에요" "~거든요" 고루 혼용.
- news_idx: 해당 뉴스의 인덱스 (0부터, 최대 {len(lv_news)-1}).

[출력] JSON만, 마크다운 코드블록 없이:
{{
  "quizzes": [
    {{
      "levelClass": "{lv}",
      "source": "{today_display} · 출처명",
      "news_idx": 0,
      "context": "2문장 배경 설명",
      "q": "질문 30자이내",
      "opts": ["보기1","보기2","보기3","보기4"],
      "ans": 0,
      "exp": "해설 HTML",
      "expert_detail": "전문가 해설 HTML"
    }}
  ]
}}"""


def fetch_quiz_from_claude(news_list):
    client     = anthropic.Anthropic()
    assignment = assign_news_to_levels(news_list)
    all_quizzes = {}

    print(f"\n🤖 [3단계] Claude 난이도별 5회 호출 시작")

    for lv in LEVELS:
        lv_news = assignment[lv]
        print(f"  [{LABELS[lv]}] 생성 중 (뉴스 {len(lv_news)}개)...")

        prompt = build_level_prompt(lv, lv_news)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10000,
            messages=[{"role": "user", "content": prompt}]
        )

        texts = [b.text for b in msg.content if hasattr(b, 'text') and b.text.strip()]
        raw   = max(texts, key=len) if texts else ""
        print(f"    응답: {len(raw)}자  stop: {msg.stop_reason}")

        if msg.stop_reason == 'max_tokens':
            print(f"    ⚠️ 토큰 초과! expert_detail 없이 재시도...")
            # expert_detail 없이 재시도
            short_prompt = prompt.replace(
                "- expert_detail 규칙:",
                "- expert_detail: <span class=\"expert-label\">🎓 박사의 한마디</span><p>관련 경제 이론과 실제 사례를 간단히 설명해요.</p><p class=\"takeaway\">핵심 정리 한 줄.</p> (이 형식 그대로, 100자 내외)\n- (원래 expert_detail 규칙 무시)"
            )
            msg2 = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=8000,
                messages=[{"role": "user", "content": short_prompt}]
            )
            texts2 = [b.text for b in msg2.content if hasattr(b, 'text') and b.text.strip()]
            raw    = max(texts2, key=len) if texts2 else raw
            print(f"    재시도 응답: {len(raw)}자  stop: {msg2.stop_reason}")

        try:
            part = _parse_json(raw)
            pool = part.get('quizzes', [])
        except Exception as e:
            print(f"    ❌ 파싱 실패: {e}")
            pool = []

        print(f"    ✅ 퀴즈 {len(pool)}개")
        all_quizzes[lv] = pool

    final = {'date': today, 'quizzes': all_quizzes}
    return _inject_urls_and_shuffle(final, news_list)


def _inject_urls_and_shuffle(data, news_list):
    assignment = assign_news_to_levels(news_list)
    quizzes    = data.get('quizzes', {})
    for lv in LEVELS:
        pool    = quizzes.get(lv, [])
        lv_news = assignment[lv]
        lv_n    = max(1, len(lv_news))
        for q in pool:
            idx  = q.get('news_idx', 0)
            news = lv_news[idx % lv_n] if lv_news else {}
            q['article_title'] = news.get('title', '')
            q['article_url']   = news.get('url',   '')
            opts = q.get('opts', [])
            ans  = q.get('ans', 0)
            if not (0 <= ans < len(opts)): ans = 0
            correct = opts[ans]
            others  = [o for j, o in enumerate(opts) if j != ans]
            random.shuffle(others)
            new_pos = random.randint(0, 3)
            others.insert(new_pos, correct)
            q['opts'] = others
            q['ans']  = new_pos
    data['quizzes'] = quizzes
    return data


# ═══════════════════════════════════════════════
# JSON 파싱 헬퍼
# ═══════════════════════════════════════════════
def _parse_json(raw):
    raw = re.sub(r'```(?:json)?\s*', '', raw).strip()
    start = raw.find('{')
    if start == -1: raise ValueError("JSON { 없음:\n" + raw[:300])
    depth, end = 0, -1
    for i, ch in enumerate(raw[start:], start):
        if ch == '{':   depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0: end = i + 1; break
    if end == -1: raise ValueError("JSON } 없음. 끝 200자:\n" + raw[-200:])
    js = raw[start:end]
    for attempt, s in enumerate([js, js.replace('\n',' ').replace('\r',''),
        ''.join(c for c in js if not unicodedata.category(c).startswith('C') or c in '\n\t').replace('\n',' ')]):
        try:
            return json.loads(s)
        except json.JSONDecodeError as e:
            if attempt == 2:
                raise ValueError(f"파싱 3회 실패: {e}\n앞500: {js[:500]}\n뒤200: {js[-200:]}")


# ═══════════════════════════════════════════════
# 저장
# ═══════════════════════════════════════════════
def save(data):
    with open('quiz_today.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    quizzes = data.get('quizzes', {})
    total   = sum(len(v) for v in quizzes.values()) if isinstance(quizzes, dict) else 0
    print(f"\n✅ quiz_today.json 저장 — 총 {total}개")
    for lv in LEVELS:
        print(f"  {LABELS[lv]}: {len(quizzes.get(lv, []))}개")


# ═══════════════════════════════════════════════
# 실행
# ═══════════════════════════════════════════════
if __name__ == '__main__':
    for key in ['ANTHROPIC_API_KEY','GEMINI_API_KEY','NAVER_CLIENT_ID','NAVER_CLIENT_SECRET']:
        if not os.environ.get(key):
            raise EnvironmentError(f"{key} 없음")

    candidates = fetch_news_from_naver()
    news_list  = select_news_with_gemini(candidates)
    quiz_data  = fetch_quiz_from_claude(news_list)
    save(quiz_data)
    print("\n🎉 완료!")
