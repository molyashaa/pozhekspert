"""
ИИ-помощник (п. 5.8 ТЗ) — интеллектуальный прототип поиска похожих замечаний.

Это НЕ самообучающаяся нейросеть и не внешний ИИ-сервис: документы компании
никуда не передаются. Алгоритм:
  1) текст приводится к нижнему регистру, знаки препинания удаляются;
  2) слова приводятся к основе простым русским стеммером, стоп-слова отбрасываются;
  3) строится TF-IDF по основам слов и по символьным n-граммам (scikit-learn);
  4) считается косинусное сходство запроса с каждой записью архива;
  5) показываются не более AI_MAX_RESULTS лучших записей выше порога AI_THRESHOLD.
Если scikit-learn не установлен, используется резервный алгоритм — коэффициент
совпадения ключевых слов (Жаккар). Индекс пересчитывается при каждом поиске,
поэтому исключённая из архива запись сразу перестаёт участвовать в выдаче.
"""
import re

from django.conf import settings

import importlib.util

# scikit-learn подключается только в момент поиска (экономия памяти на хостинге)
HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None

STOP_WORDS = set("""
и в во не на но что с со как а то все она так его же от по к ко у из за для о об при без до или ли
бы был была были быть это этот эта эти тот та те там тут нет да же уже еще ещё только также так
который которая которые которых его ее её их им ими мы вы он они оно себя свой своя свои под над
между через после перед более менее очень можно нужно надо есть нет при всех всего каждый каждая
""".split())

_SUFFIXES = sorted("""
иями ями ами ием ием иях ях ах ией ией ией ого его ому ему ыми ими ая яя ое ее ые ие ый ий ой ую юю
ом ем ам ям ов ев ей ию ия ья ье ьи ью ия ии ие ях ах ы и а я о е у ю ь й ость ости остью ение ения
ении ением ениям ениями ание ания ании анием аниям ться тся ить ать ять еть уть ешь ет ют ят ит ут ем им
ал ала али ало ил ила или ило ый ые ов
""".split(), key=len, reverse=True)


def stem(word):
    """Очень простой стеммер: отсекает типичные окончания, оставляя основу ≥ 4 букв."""
    if len(word) <= 4:
        return word
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            return word[: -len(suf)]
    return word


def tokenize(text):
    text = (text or "").lower().replace("ё", "е")
    words = re.findall(r"[a-zа-я0-9]+", text)
    return [w for w in words if w not in STOP_WORDS and len(w) > 2]


def normalize(text):
    return " ".join(stem(w) for w in tokenize(text))


def _entry_text(entry):
    return " ".join(filter(None, [entry.title, entry.text, entry.category, entry.stage_type]))


def common_words(query, entry_text, limit=4):
    """Объяснение сходства: слова запроса, основы которых встречаются в записи архива."""
    entry_stems = {stem(w) for w in tokenize(entry_text)}
    found, seen = [], set()
    for w in tokenize(query):
        s = stem(w)
        if s in entry_stems and s not in seen:
            seen.add(s)
            found.append(w)
    return found[:limit]


def search(query, entries, stage_type="", doc_type=""):
    """
    entries — список записей архива, уже отфильтрованный по правам пользователя.
    Возвращает (results, info): results — список словарей с записью и оценкой.
    """
    entries = list(entries)
    threshold = settings.AI_THRESHOLD
    info = {"threshold": round(threshold * 100), "algorithm": "TF-IDF + косинусное сходство" if HAS_SKLEARN
            else "ключевые слова (резервный алгоритм)", "total": len(entries)}
    query_norm = normalize(query)
    if not query_norm or not entries:
        return [], info

    docs = [entry.normalized_text or normalize(_entry_text(entry)) for entry in entries]
    if HAS_SKLEARN:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        corpus = docs + [query_norm]
        word_vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True)
        char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        w = word_vec.fit_transform(corpus)
        c = char_vec.fit_transform(corpus)
        w_scores = cosine_similarity(w[-1], w[:-1])[0]
        c_scores = cosine_similarity(c[-1], c[:-1])[0]
        scores = [0.55 * a + 0.45 * b for a, b in zip(w_scores, c_scores)]
    else:
        q = set(query_norm.split())
        scores = []
        for d in docs:
            s = set(d.split())
            scores.append(len(q & s) / len(q | s) if q | s else 0.0)

    results = []
    for entry, score in zip(entries, scores):
        bonus = 0.0
        if stage_type and entry.stage_type and stage_type.lower() in entry.stage_type.lower():
            bonus += 0.05
        if doc_type and entry.doc_type == doc_type:
            bonus += 0.05
        total = min(float(score) + (bonus if score > 0.1 else 0), 1.0)
        if total >= threshold:
            results.append({
                "entry": entry,
                "score": round(total * 100),
                "words": common_words(query, _entry_text(entry)),
            })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[: settings.AI_MAX_RESULTS], info
