"""Pages: tournament list, game list, and the tournament scoreboard."""

from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from leefanniv.models import Game, Match, Outcome, Player, Result, Tournament


class TournamentForm(forms.ModelForm):
    class Meta:
        model = Tournament
        fields = ["name"]


class GameForm(forms.ModelForm):
    class Meta:
        model = Game
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
    ctx = {"tournaments": Tournament.objects.all(), "form": form}
    return render(request, "leefanniv/tournaments.html", ctx)


def games(request: HttpRequest) -> HttpResponse:
    """List games with their point scale and add a new one."""
    form = GameForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("games")
    return render(
        request, "leefanniv/games.html", {"games": Game.objects.all(), "form": form}
    )


def tournament(request: HttpRequest, pk: int) -> HttpResponse:
    """Show a tournament's scoreboard and handle its edit actions."""
    t = get_object_or_404(Tournament, pk=pk)
    players = Player.objects.filter(team__tournament=t).select_related("team")
    if request.method == "POST":
        _handle_action(request, t, players)
        return redirect("tournament", t.pk)
    ctx = {
        "t": t,
        "tournaments": Tournament.objects.all(),
        "ranking": t.ranking(),
        "teams": t.teams.prefetch_related("players"),
        "games": Game.objects.all(),
        "matches": t.matches.select_related("game").prefetch_related(
            "results__player__team"
        )[:30],
    }
    return render(request, "leefanniv/tournament.html", ctx)


def _handle_action(request: HttpRequest, t: Tournament, players) -> None:
    """Apply one POSTed action to tournament *t*, reporting through messages."""
    post = request.POST
    action = post.get("action")
    name = post.get("name", "").strip()
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
    elif action == "match":
        game = Game.objects.filter(pk=post.get("game")).first()
        valid = set(Outcome.values)
        picks = {p: post.get(f"p{p.pk}") for p in players}
        picks = {p: o for p, o in picks.items() if o in valid}
        if game is None or not picks:
            messages.error(request, "Il faut un jeu et au moins un joueur.")
            return
        with transaction.atomic():
            match = Match.objects.create(tournament=t, game=game)
            Result.objects.bulk_create(
                Result(match=match, player=p, outcome=o) for p, o in picks.items()
            )
        messages.success(request, f"Match de {game} enregistré.")
    elif action == "delete_match":
        t.matches.filter(pk=post.get("match")).delete()
