"""Data model: games, tournaments, their teams and players, and match results.

A tournament is either a points competition or a knockout bracket.

In a points competition, a match pits teams against each other, each engaging
the same number of players. A team earns the charter's rate for its outcome
times the number of players engaged in the whole match, and each of its engaged
players is credited with that same gain.
Points are read from the charter at ranking time, so editing it re-scores past
matches too.

A bracket is stored as every match of every round, created up front: the later
rounds start empty and are filled as winners are picked.
"""

from __future__ import annotations

import random
from collections import Counter
from decimal import Decimal
from typing import Any

from django.db import models, transaction


class Outcome(models.TextChoices):
    WIN = "W", "Victoire"
    DRAW = "D", "Égalité"
    LOSS = "L", "Défaite"


class Kind(models.TextChoices):
    POINTS = "points", "Classement à points"
    BRACKET = "bracket", "Tableau à élimination"


# Pastel team colours, assigned by team id.
PALETTE = [
    "#ffb3c6",
    "#a0d8ff",
    "#b5ead7",
    "#ffd6a5",
    "#cdb4ff",
    "#fff1a8",
    "#9ff0f0",
    "#ffc6ff",
]


class Game(models.Model):
    name = models.CharField("nom", max_length=100, unique=True)
    emoji = models.CharField(max_length=8, default="🎲")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Tournament(models.Model):
    name = models.CharField("nom du tournoi", max_length=100)
    kind = models.CharField(
        "type", max_length=10, choices=Kind.choices, default=Kind.POINTS
    )
    created = models.DateTimeField(auto_now_add=True)
    # The charter: per outcome, points per player engaged in the whole match.
    win_points = models.DecimalField(
        "victoire", max_digits=5, decimal_places=1, default=Decimal(1)
    )
    draw_points = models.DecimalField(
        "égalité", max_digits=5, decimal_places=1, default=Decimal("0.5")
    )
    loss_points = models.DecimalField(
        "défaite", max_digits=5, decimal_places=1, default=Decimal(0)
    )

    class Meta:
        ordering = ["-created"]

    def __str__(self) -> str:
        return self.name

    def remove(self) -> None:
        """Delete the tournament with its matches, bracket, teams and players.

        Results and bracket slots protect the players and teams they name, so
        they go first; the rest follows by cascade.
        """
        with transaction.atomic():
            self.matches.all().delete()
            self.bracket.all().delete()
            self.delete()

    def points(self, outcome: str) -> Decimal:
        """Return the charter rate for *outcome*, per player in the match."""
        return {
            Outcome.WIN: self.win_points,
            Outcome.DRAW: self.draw_points,
            Outcome.LOSS: self.loss_points,
        }[Outcome(outcome)]

    def record_match(
        self, game: Game, lineups: dict[Team, list[Player]], winner: Team | None
    ) -> Match:
        """Record a team-against-team match.

        Parameters
        ----------
        game
            The game played.
        lineups
            The engaged players of each team taking part.
        winner
            The winning team, or ``None`` for a draw.

        Returns
        -------
        Match
            The recorded match.

        Raises
        ------
        ValueError
            If fewer than two teams play, their lineups differ in size, or the
            winner is not one of them.
        """
        if len(lineups) < 2:
            raise ValueError("Il faut au moins deux équipes.")
        sizes = {len(players) for players in lineups.values()}
        if len(sizes) != 1 or 0 in sizes:
            raise ValueError("Chaque équipe doit engager le même nombre de joueurs.")
        if winner is not None and winner not in lineups:
            raise ValueError("L'équipe gagnante doit faire partie du match.")
        with transaction.atomic():
            match = self.matches.create(game=game)
            Result.objects.bulk_create(
                Result(match=match, player=p, outcome=_outcome(team, winner))
                for team, players in lineups.items()
                for p in players
            )
        return match

    def standings(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return the team ranking and the player ranking, best first.

        A match is worth the charter's rate for an outcome times the number of
        players it engaged, all teams included. Each team earns that for its
        outcome, and so does each of its engaged players.

        Returns
        -------
        teams, players : list of dict
            Keys ``obj`` (the team or player), ``points``, ``played`` and one
            count per outcome code (``W``, ``D``, ``L``). For a team, ``played``
            counts matches, not engaged players. Ties are broken by name.
        """
        teams = {t.pk: _row(t) for t in self.teams.all()}
        players = {
            p.pk: _row(p)
            for p in Player.objects.filter(team__tournament=self).select_related("team")
        }
        seen: set[tuple[int, int]] = set()
        results = list(
            Result.objects.filter(match__tournament=self).select_related("player")
        )
        engaged = Counter(r.match_id for r in results)
        for r in results:
            gain = self.points(r.outcome) * engaged[r.match_id]
            prow, trow = players[r.player_id], teams[r.player.team_id]
            prow[r.outcome] += 1
            prow["played"] += 1
            prow["points"] += gain
            if (r.match_id, r.player.team_id) not in seen:
                seen.add((r.match_id, r.player.team_id))
                trow[r.outcome] += 1
                trow["played"] += 1
                trow["points"] += gain

        def order(rows: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
            return sorted(rows.values(), key=lambda r: (-r["points"], r["obj"].name))

        return order(teams), order(players)

    def start_bracket(self) -> None:
        """Draw the teams at random into a fresh bracket.

        Raises
        ------
        ValueError
            If the team count is not a power of two of at least 2.
        """
        teams = list(self.teams.all())
        n = len(teams)
        if n < 2 or n & (n - 1):
            raise ValueError("Il faut 2, 4, 8, 16… équipes pour un tableau.")
        random.shuffle(teams)
        self.bracket.all().delete()
        size, rnd = n // 2, 0
        while size:
            BracketMatch.objects.bulk_create(
                BracketMatch(tournament=self, round=rnd, slot=i) for i in range(size)
            )
            size, rnd = size // 2, rnd + 1
        for i, match in enumerate(self.bracket.filter(round=0)):
            match.team_a, match.team_b = teams[2 * i], teams[2 * i + 1]
            match.save()

    def bracket_rounds(self) -> list[dict[str, Any]]:
        """Return the bracket as rounds, first round first.

        Returns
        -------
        list of dict
            Keys ``label`` (e.g. ``"Demi-finales"``) and ``matches``.
        """
        matches = list(self.bracket.select_related("team_a", "team_b", "winner"))
        count = max((m.round for m in matches), default=-1) + 1
        return [
            {
                "label": round_label(count - r),
                "matches": [m for m in matches if m.round == r],
            }
            for r in range(count)
        ]


def _row(obj: Team | Player) -> dict[str, Any]:
    return {"obj": obj, "points": Decimal(0), "played": 0, "W": 0, "D": 0, "L": 0}


def _outcome(team: Team, winner: Team | None) -> str:
    """Return the outcome code (see :class:`Outcome`) of *team* in a match."""
    if winner is None:
        return "D"
    return "W" if team == winner else "L"


def round_label(left: int) -> str:
    """Name a round by how many rounds remain, the final included."""
    names = {1: "Finale", 2: "Demi-finales", 3: "Quarts", 4: "Huitièmes"}
    return names.get(left, f"1/{2 ** (left - 1)}es")


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

    @property
    def color(self) -> str:
        return PALETTE[(self.pk or 0) % len(PALETTE)]

    @property
    def initials(self) -> str:
        return "".join(w[0] for w in self.name.split()[:2]).upper()


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

    @property
    def lineups(self) -> list[tuple[Team, list[Player], str]]:
        """Return ``(team, players, outcome)`` per team, in result order."""
        groups: dict[Team, tuple[list[Player], str]] = {}
        for r in self.results.all():
            groups.setdefault(r.player.team, ([], r.outcome))[0].append(r.player)
        return [(team, ps, outcome) for team, (ps, outcome) in groups.items()]


class Result(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="results")
    player = models.ForeignKey(Player, on_delete=models.PROTECT)
    outcome = models.CharField(max_length=1, choices=Outcome.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["match", "player"], name="uniq_result")
        ]


class BracketMatch(models.Model):
    tournament = models.ForeignKey(
        Tournament, on_delete=models.CASCADE, related_name="bracket"
    )
    round = models.PositiveSmallIntegerField()
    slot = models.PositiveSmallIntegerField()
    team_a = models.ForeignKey(
        Team, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    team_b = models.ForeignKey(
        Team, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    winner = models.ForeignKey(
        Team, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["round", "slot"]
        constraints = [
            models.UniqueConstraint(
                fields=["tournament", "round", "slot"], name="uniq_bracket_slot"
            )
        ]

    def __str__(self) -> str:
        return f"{self.tournament} R{self.round} #{self.slot}"

    @property
    def sides(self) -> list[tuple[Team | None, Team | None]]:
        """Return ``(team, opponent)`` for both slots, for display."""
        return [(self.team_a, self.team_b), (self.team_b, self.team_a)]

    def set_winner(self, team: Team | None) -> None:
        """Record *team* as the winner (``None`` to undo) and advance it.

        Raises
        ------
        ValueError
            If *team* does not play this match.
        """
        if team is not None and team.pk not in (self.team_a_id, self.team_b_id):
            raise ValueError("Cette équipe ne joue pas ce match.")
        self.winner = team
        self.save()
        self._feed(team)

    def _feed(self, team: Team | None) -> None:
        """Put *team* into the next round, voiding results it invalidates."""
        nxt = BracketMatch.objects.filter(
            tournament_id=self.tournament_id, round=self.round + 1, slot=self.slot // 2
        ).first()
        if nxt is None:
            return
        field = "team_a_id" if self.slot % 2 == 0 else "team_b_id"
        new = team.pk if team else None
        if getattr(nxt, field) == new:
            return
        setattr(nxt, field, new)
        # The line-up changed, so the next match's result no longer holds.
        had_winner = nxt.winner_id is not None
        nxt.winner = None
        nxt.save()
        if had_winner:
            nxt._feed(None)
