from app.schemas import Vacancy


def matches(vacancy: Vacancy, kw: dict) -> bool:
    text = f"{vacancy.title} {vacancy.location}".lower()
    include = [k.lower() for k in kw.get("include", [])]
    exclude = [k.lower() for k in kw.get("exclude", [])]
    if any(x in text for x in exclude):
        return False
    if not include:
        return True
    if kw.get("match", "any") == "all":
        return all(i in text for i in include)
    return any(i in text for i in include)


def filter_vacancies(vacancies: list[Vacancy], kw: dict) -> list[Vacancy]:
    return [v for v in vacancies if matches(v, kw)]
