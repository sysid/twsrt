"""Canonical-source profile expansion."""

from __future__ import annotations

from twsrt.lib.models import AppConfig, ResolvedProfile


def resolve_profile(
    config: AppConfig, profile_name: str | None = None
) -> ResolvedProfile:
    """Resolve profile inheritance into ordered fragment selections."""
    selected = profile_name or config.default_profile
    if selected is None or selected not in config.profiles:
        available = ", ".join(sorted(config.profiles)) or "(none configured)"
        raise ValueError(f"Unknown profile {selected!r}; available: {available}")

    names: dict[str, list[str]] = {kind: [] for kind in config.sources}
    visited: set[str] = set()

    def walk(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        profile = config.profiles[name]
        for parent in profile.extends:
            walk(parent)
        for kind, selected_names in profile.selections.items():
            for fragment_name in selected_names:
                if fragment_name not in names[kind]:
                    names[kind].append(fragment_name)

    walk(selected)
    for kind, selected_names in names.items():
        if not selected_names:
            raise ValueError(
                f"Profile {selected!r} selects no fragments for source kind {kind!r}"
            )

    return ResolvedProfile(
        name=selected,
        fragments={
            kind: [config.sources[kind].fragments[name] for name in selected_names]
            for kind, selected_names in names.items()
        },
    )
