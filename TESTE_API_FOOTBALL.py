from src import api_football as a
a.api_enabled=lambda: True
a._request_fixtures=lambda day:[{
    "fixture":{"id":123},
    "league":{"name":"Liga Profesional Argentina","country":"Argentina"},
    "teams":{"home":{"name":"Banfield"},"away":{"name":"Belgrano"}}
}]
r=a.enrich_from_api({"event":"Banfleld x Belgrano","competition":"","bet_date":"2026-08-10"})
print(r)
assert r["event"]=="Banfield x Belgrano"
assert r["competition"]=="Liga Profesional Argentina"
assert r["_api_fixture_id"]==123
