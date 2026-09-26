import pytest

from leefanniv.models import Game, Match, Result, Tournament


@pytest.mark.django_db
def test_ranking_sums_member_points_per_team(client):
    t = Tournament.objects.create(name="Soirée")
    red, blue = t.teams.create(name="Rouge"), t.teams.create(name="Bleu")
    alice, bob = red.players.create(name="Alice"), red.players.create(name="Bob")
    carol = blue.players.create(name="Carol")
    chess = Game.objects.create(name="Échecs", win_points=3, draw_points=1)
    darts = Game.objects.create(name="Fléchettes", win_points=5, loss_points=-1)

    m1 = Match.objects.create(tournament=t, game=chess)
    Result.objects.create(match=m1, player=alice, outcome="D")
    Result.objects.create(match=m1, player=carol, outcome="D")
    m2 = Match.objects.create(tournament=t, game=darts)
    Result.objects.create(match=m2, player=bob, outcome="L")
    Result.objects.create(match=m2, player=carol, outcome="W")

    rows = t.ranking()
    assert [(r["team"].name, r["points"], r["played"]) for r in rows] == [
        ("Bleu", 6, 2),
        ("Rouge", 0, 2),
    ]
    assert client.get(f"/t/{t.pk}/").status_code == 200


@pytest.mark.django_db
def test_record_match_via_post(client):
    t = Tournament.objects.create(name="Soirée")
    p = t.teams.create(name="Rouge").players.create(name="Alice")
    g = Game.objects.create(name="Uno")
    client.post(f"/t/{t.pk}/", {"action": "match", "game": g.pk, f"p{p.pk}": "W"})
    assert t.ranking()[0]["points"] == 3
