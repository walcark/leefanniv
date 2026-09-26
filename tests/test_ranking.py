from decimal import Decimal

import pytest

from leefanniv.models import Game, Match, Tournament


@pytest.mark.django_db
def test_charter_points_scale_with_engaged_players(client):
    t = Tournament.objects.create(name="Soirée")  # charter: 1 / 0.5 / 0 per player
    red, blue = t.teams.create(name="Rouge"), t.teams.create(name="Bleu")
    alice, bob = red.players.create(name="Alice"), red.players.create(name="Bob")
    carol, dan = blue.players.create(name="Carol"), blue.players.create(name="Dan")
    smash = Game.objects.create(name="Smash")

    t.record_match(smash, {red: [alice, bob], blue: [carol, dan]}, winner=red)
    t.record_match(smash, {red: [alice], blue: [carol]}, winner=None)

    teams, players = t.standings()
    assert [(r["obj"].name, r["points"], r["played"], r["W"]) for r in teams] == [
        ("Rouge", Decimal("2.5"), 2, 1),
        ("Bleu", Decimal("0.5"), 2, 0),
    ]
    assert [(r["obj"].name, r["points"]) for r in players][:2] == [
        ("Alice", Decimal("1.5")),
        ("Bob", Decimal("1")),
    ]
    assert client.get(f"/t/{t.pk}/").status_code == 200
    charter = client.get(f"/t/{t.pk}/charte/").content.decode()
    assert "obligatoire" not in charter and 'value="Soirée"' in charter


@pytest.mark.django_db
def test_record_match_rejects_uneven_lineups():
    t = Tournament.objects.create(name="Soirée")
    red, blue = t.teams.create(name="Rouge"), t.teams.create(name="Bleu")
    a, b = red.players.create(name="A"), red.players.create(name="B")
    c = blue.players.create(name="C")
    with pytest.raises(ValueError):
        t.record_match(Game.objects.create(name="Uno"), {red: [a, b], blue: [c]}, red)
    assert not Match.objects.exists()


@pytest.mark.django_db
def test_record_match_via_post(client):
    t = Tournament.objects.create(name="Soirée", win_points=3)
    red, blue = t.teams.create(name="Rouge"), t.teams.create(name="Bleu")
    a, c = red.players.create(name="A"), blue.players.create(name="C")
    g = Game.objects.create(name="Uno")
    post = {"action": "match", "game": g.pk, "players": [a.pk, c.pk], "winner": red.pk}
    client.post(f"/t/{t.pk}/", post)
    assert t.standings()[0][0]["points"] == 3


@pytest.mark.django_db
def test_bracket_advances_winners_and_voids_stale_results(client):
    t = Tournament.objects.create(name="Coupe", kind="bracket")
    for name in "ABCD":
        t.teams.create(name=name)
    t.start_bracket()
    semi1, semi2, final = t.bracket.all()
    semi1.set_winner(semi1.team_a)
    semi2.set_winner(semi2.team_b)
    final.refresh_from_db()
    assert (final.team_a, final.team_b) == (semi1.team_a, semi2.team_b)
    final.set_winner(final.team_a)

    # Changing a semi-final winner replaces the finalist and voids the final.
    semi1.set_winner(semi1.team_b)
    final.refresh_from_db()
    assert final.team_a == semi1.team_b and final.winner is None
    assert [r["label"] for r in t.bracket_rounds()] == ["Demi-finales", "Finale"]
    assert client.get(f"/t/{t.pk}/").status_code == 200


@pytest.mark.django_db
def test_bracket_needs_power_of_two_teams():
    t = Tournament.objects.create(name="Coupe", kind="bracket")
    for name in "ABC":
        t.teams.create(name=name)
    with pytest.raises(ValueError):
        t.start_bracket()


@pytest.mark.django_db
def test_delete_game_only_when_never_played(client):
    t = Tournament.objects.create(name="Soirée")
    red, blue = t.teams.create(name="Rouge"), t.teams.create(name="Bleu")
    a, c = red.players.create(name="A"), blue.players.create(name="C")
    typo, played = Game.objects.create(name="Smsh"), Game.objects.create(name="Uno")
    t.record_match(played, {red: [a], blue: [c]}, red)
    for g in (typo, played):
        client.post(f"/t/{t.pk}/", {"action": "delete_game", "game": g.pk})
    assert list(Game.objects.values_list("name", flat=True)) == ["Uno"]


@pytest.mark.django_db
def test_screen_live_block_is_stable_between_polls(client):
    # The screen swaps its live block whenever the HTML differs, so anything
    # per-request in it (a CSRF token) would make it redraw every second.
    for kind in ("points", "bracket"):
        t = Tournament.objects.create(name="Soirée", kind=kind)
        for name in "AB":
            t.teams.create(name=name).players.create(name=name.lower())
        if kind == "bracket":
            t.start_bracket()
        first, second = (client.get(f"/t/{t.pk}/ecran/").content for _ in range(2))
        assert first == second and b"csrfmiddlewaretoken" not in first


@pytest.mark.django_db
def test_delete_tournament_frees_its_games(client):
    t = Tournament.objects.create(name="Test", kind="bracket")
    red, blue = t.teams.create(name="Rouge"), t.teams.create(name="Bleu")
    a, c = red.players.create(name="A"), blue.players.create(name="C")
    g = Game.objects.create(name="JEU1")
    t.record_match(g, {red: [a], blue: [c]}, red)
    t.start_bracket()
    t.bracket.first().set_winner(red)
    client.post(f"/t/{t.pk}/equipes/", {"action": "delete_tournament"})
    assert not Tournament.objects.exists() and not Match.objects.exists()
    assert not g.match_set.exists()
