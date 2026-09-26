"""Pages: the tournament list and a tournament's tabs (play, teams, charter)."""

from collections import defaultdict

from django import forms
from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import floatformat

from leefanniv.models import (
    BracketMatch,
    Game,
    Kind,
    Player,
    Team,
    Tournament,
)


class TournamentForm(forms.ModelForm):
    class Meta:
        model = Tournament
        fields = ["name", "kind"]


class CharterForm(forms.ModelForm):
    class Meta:
        model = Tournament
        fields = ["name", "win_points", "draw_points", "loss_points"]


def home(request: HttpRequest) -> HttpResponse:
    """Open the latest tournament, or the list when there is none yet."""
    latest = Tournament.objects.first()
    return redirect("tournament", latest.pk) if latest else redirect("tournaments")


def tournaments(request: HttpRequest) -> HttpResponse:
    """List tournaments and create a new one."""
    form = TournamentForm(request.POST or None)
    if form.is_valid():
        return redirect("tournament", form.save().pk)
    ctx = {
        "tournaments": Tournament.objects.prefetch_related("teams"),
        "form": form,
        "kinds": Kind.choices,
    }
    return render(request, "leefanniv/tournaments.html", ctx)


def tournament(request: HttpRequest, pk: int, tab: str = "play") -> HttpResponse:
    """Show one tab of a tournament and handle its edit actions."""
    t = get_object_or_404(Tournament, pk=pk)
    posted = request.POST if request.method == "POST" else None
    charter = CharterForm(posted if tab == "charter" else None, instance=t)
    if request.method == "POST":
        if request.POST.get("action") == "delete_tournament":
            t.remove()
            messages.success(request, f"Compétition « {t.name} » supprimée.")
            return redirect("tournaments")
        if tab == "charter":
            if charter.is_valid():
                charter.save()
                messages.success(request, "Charte enregistrée.")
                return redirect("charter", t.pk)
        else:
            return redirect(_handle_action(request, t))
    team_rows, player_rows = t.standings()
    top = max((r["points"] for r in team_rows), default=0)
    for r in team_rows:
        r["pct"] = int(max(r["points"], 0) * 100 / top) if top > 0 else 0
    ctx = {
        "t": t,
        "tab": tab,
        "charter": charter,
        "team_rows": team_rows,
        "player_rows": player_rows,
        "rounds": t.bracket_rounds(),
        "power_of_two": _is_power_of_two(t.teams.count()),
        "teams": t.teams.prefetch_related("players"),
        "players": Player.objects.filter(team__tournament=t),
        "games": Game.objects.annotate(
            played=Count("match", filter=Q(match__tournament=t)),
            used=Count("match"),
        ),
        "picked_game": request.GET.get("game", ""),
        "examples": [
            (n, t.win_points * 2 * n, t.draw_points * 2 * n, t.loss_points * 2 * n)
            for n in (1, 2, 3)
        ],
        "match_count": t.matches.count(),
        "matches": t.matches.select_related("game").prefetch_related(
            "results__player__team"
        )[:30],
    }
    page = "screen" if tab == "screen" else "tournament"
    return render(request, f"leefanniv/{page}.html", ctx)


def _handle_action(request: HttpRequest, t: Tournament) -> str:
    """Apply one POSTed action to *t*; return the URL to go back to."""
    post = request.POST
    action = post.get("action")
    name = post.get("name", "").strip()
    back = request.path
    if action == "team":
        if not name or t.teams.filter(name=name).exists():
            messages.error(request, "Nom d'équipe vide ou déjà pris.")
        else:
            t.teams.create(name=name)
    elif action == "player":
        team = t.teams.filter(pk=post.get("team")).first()
        if not name or team is None:
            messages.error(request, "Il faut un nom et une équipe.")
        else:
            team.players.create(name=name)
    elif action == "game":
        if not name or Game.objects.filter(name__iexact=name).exists():
            messages.error(request, "Nom de jeu vide ou déjà pris.")
        else:
            Game.objects.create(name=name, emoji=post.get("emoji", "").strip() or "🎲")
        back += "#jeux"
    elif action == "delete_game":
        game = Game.objects.filter(pk=post.get("game")).first()
        if game is None or game.match_set.exists():
            messages.error(
                request, "Ce jeu a déjà été joué, il ne peut pas être retiré."
            )
        else:
            game.delete()
            messages.success(request, f"{game.emoji} {game} retiré de la liste.")
        back += "#jeux"
    elif action == "match":
        back = _record_match(request, t)
    elif action == "delete_match":
        t.matches.filter(pk=post.get("match")).delete()
        back += "#match"
    elif action == "start_bracket":
        try:
            t.start_bracket()
        except ValueError as exc:
            messages.error(request, str(exc))
    elif action == "reset_bracket":
        t.bracket.all().delete()
    elif action == "winner":
        match = get_object_or_404(BracketMatch, tournament=t, pk=post.get("match"))
        team = t.teams.filter(pk=post.get("team")).first()
        # Tapping the current winner again undoes the pick.
        match.set_winner(None if team is None or team == match.winner else team)
    return back


def _record_match(request: HttpRequest, t: Tournament) -> str:
    """Record the POSTed match; return the URL to go back to."""
    post = request.POST
    game = Game.objects.filter(pk=post.get("game")).first()
    chosen = Player.objects.filter(
        team__tournament=t, pk__in=post.getlist("players")
    ).select_related("team")
    lineups: dict[Team, list[Player]] = defaultdict(list)
    for p in chosen:
        lineups[p.team].append(p)
    raw_winner = post.get("winner")
    winner = None if raw_winner == "draw" else t.teams.filter(pk=raw_winner).first()
    back = f"{request.path}#match"
    if game is None:
        messages.error(request, "Choisis un jeu.")
        return back
    if raw_winner != "draw" and winner is None:
        messages.error(request, "Choisis l'équipe gagnante ou l'égalité.")
        return back
    try:
        t.record_match(game, lineups, winner)
    except ValueError as exc:
        messages.error(request, str(exc))
        return back
    engaged = sum(len(players) for players in lineups.values())
    if winner is None:
        gain = floatformat(t.draw_points * engaged, -1)
        messages.success(request, f"{game.emoji} {game} : égalité, +{gain} par équipe")
    else:
        gain = floatformat(t.win_points * engaged, -1)
        messages.success(request, f"{game.emoji} {game} : {winner} gagne, +{gain}")
    return f"{request.path}?game={game.pk}#match"


def _is_power_of_two(n: int) -> bool:
    return n >= 2 and not n & (n - 1)
