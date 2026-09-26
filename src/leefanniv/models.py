"""Data model: games, tournaments, their teams and players, and match results.

A match records one outcome per participating player; each outcome earns the
player's team the game's points for it. Points are read from the game at
ranking time, so editing a game's scale re-scores past matches too.
"""

from __future__ import annotations

from typing import Any

from django.db import models


class Outcome(models.TextChoices):
    WIN = "W", "Victoire"
    DRAW = "D", "Égalité"
    LOSS = "L", "Défaite"


class Game(models.Model):
    name = models.CharField("nom", max_length=100, unique=True)
    win_points = models.IntegerField("points victoire", default=3)
    draw_points = models.IntegerField("points égalité", default=1)
    loss_points = models.IntegerField("points défaite", default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def points(self, outcome: str) -> int:
        """Return the points this game awards for *outcome*."""
        return {
            Outcome.WIN: self.win_points,
            Outcome.DRAW: self.draw_points,
            Outcome.LOSS: self.loss_points,
        }[Outcome(outcome)]


class Tournament(models.Model):
    name = models.CharField("nom du tournoi", max_length=100)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self) -> str:
        return self.name

    def ranking(self) -> list[dict[str, Any]]:
        """Return one row per team, best first.

        Returns
        -------
        list of dict
            Keys ``team``, ``points``, ``played`` and one count per outcome
            code (``W``, ``D``, ``L``). Ties on points are broken by name.
        """
        rows = {
            team.pk: {"team": team, "points": 0, "played": 0, "W": 0, "D": 0, "L": 0}
            for team in self.teams.all()
        }
        results = Result.objects.filter(match__tournament=self).select_related(
            "match__game", "player"
        )
        for result in results:
            row = rows[result.player.team_id]
            row[result.outcome] += 1
            row["played"] += 1
            row["points"] += result.match.game.points(result.outcome)
        return sorted(rows.values(), key=lambda r: (-r["points"], r["team"].name))


class Team(models.Model):
    tournament = models.ForeignKey(
        Tournament, on_delete=models.CASCADE, related_name="teams"
    )
    name = models.CharField("nom", max_length=100)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tournament", "name"], name="uniq_team")
        ]

    def __str__(self) -> str:
        return self.name


class Player(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="players")
    name = models.CharField("nom", max_length=100)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Match(models.Model):
    tournament = models.ForeignKey(
        Tournament, on_delete=models.CASCADE, related_name="matches"
    )
    # PROTECT: deleting a game or a player must not silently rewrite scores.
    game = models.ForeignKey(Game, on_delete=models.PROTECT)
    played_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-played_at"]
        verbose_name_plural = "matches"

    def __str__(self) -> str:
        return f"{self.game} ({self.played_at:%d/%m %H:%M})"


class Result(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="results")
    player = models.ForeignKey(Player, on_delete=models.PROTECT)
    outcome = models.CharField(max_length=1, choices=Outcome.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["match", "player"], name="uniq_result")
        ]
