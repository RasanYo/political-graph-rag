# TODO

`[ ]` à faire · `[.]` en cours · `[x]` fait → descend dans la liste du bas.

Une tâche qui tourne sans ligne ici est invisible — pour toi pendant qu'elle
tourne, pour la session suivante une fois qu'elle s'arrête. Avant de toucher
quoi que ce soit, cherche la tâche ici ; si elle n'y est pas, ajoute-la, une
ligne, la même voix que ses voisines, et passe-la `[.]` avant la première
édition. Terminée : `[x]`, datée, déplacée dans `## Fait`. Abandonnée : la ligne
revient à `[ ]` — un `[.]` mort est pire que pas de ligne.

La barre : ce qui change ce que le système *est* ou *sait faire*. Une question,
une synchro de config, une coquille, un correctif d'un seul fichier — pas de
ligne, on le fait.

- [ ] Trouver et obtenir le corpus — quelles archives, quelle licence, quelle fenêtre
- [ ] Récupérer les références de validation (Smartvote, votes nominatifs, MARPOR/CHES)
- [ ] Poser le squelette du repo — arborescence `src/`, `scripts/`, `data/`
- [ ] Représenter les résultats en graphe — le biparti média–acteur qui porte la
      mesure, et sa projection média–média qui porte le résultat. L'arête entre
      deux médias dit co-positionnement, jamais influence : undirected, et la
      version résiduelle après VARX à côté de la brute.
- [.] Explorer pas à pas NER puis ton ciblé — DE seul, une votation du bloc A
      (A-631), toutes personnes et organisations, ton *envers* l'acteur
      seulement. Quelques modèles choisis à la main par étape, chaque sortie
      lue avant de passer à la suivante.
- [ ] Prototyper le ton ciblé par fenêtre de mention — Cardiff XLM-R sur ±1
      phrase autour de chaque mention, une fenêtre, une langue, un outlet. Deux
      acteurs dans la même phrase reçoivent le même score : limite admise, pas
      un bug. Le verdict n'est pas le F1 mais le diagnostic DE/FR — si le ton
      diffère systématiquement entre langues pour les mêmes acteurs, on mesure
      la langue, pas le ton.
- [ ] Si la fenêtre tient : fine-tuner XLM-R sur NewsMTSC pour le ton ciblé — le
      modèle prend (texte, cible) et rend un score par acteur, ce que la fenêtre
      ne sait pas faire. NewsMTSC est anglais seul : tout repose sur le transfert
      cross-lingue vers DE/FR, hypothèse à tester, jamais acquise.

## Fait

*On coupe à 3 mois. Plus ancien, ça vit dans le `DEVLOG.md`.*

- [x] 2026-09-14 — Le répertoire d'événements d'amorçage
      20 événements (8 votations, 4 élections du Conseil fédéral, 3 suisses hors
      calendrier, 1 contrôle consensuel, 4 internationaux en diagnostic), choisis
      par une règle mécanique sur polarisation × Röstigraben. 304 lignes
      d'entités, 65 QID, aucune appariée par chaîne de caractères. Deux runs
      donnent des CSV identiques au byte près. 20 requêtes Swissdox validées,
      zéro article téléchargé.

- [x] 2026-09-11 — L'environnement Python et le manifeste de dépendances
      Python 3.12 dans `.venv`, `pyproject.toml` + `uv.lock` versionnés, le
      paquet `mediapos` sous `src/` installé en editable. Reconstruit depuis
      zéro avec `uv sync --frozen` pour vérifier que le lock suffit.

- [x] 2026-09-11 — Le sujet est cadré
      positionnement politique des médias suisses par la *visibilité* des acteurs,
      pas par le contenu. Le proposal vit dans `docs/proposal.md`, les règles qui
      en découlent dans `CLAUDE.md` — dont la portée honnête : on caractérise le
      co-positionnement, on ne prouve aucune contagion.
- [x] 2026-09-11 — L'outillage porté depuis `ai-trading-algo`
      `TODO.md` et `DEVLOG.md` comme planche et trace, le `.claude/` générique
      (commandes, sous-agents, skills `ship-feature`, règles Python, hook
      DEVLOG après merge), et Ralph activé. Ce qui était propre au trading —
      skills `strategy-*`, `data-sourcing`, `audit-bias` — n'a pas suivi.
