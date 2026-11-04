# DEVLOG

Trace chronologique du travail effectué, la plus récente en premier. Une entrée
par lot de travail fusionné dans `develop` qui change ce que le système *est* ou
*peut faire* — le *pourquoi* et le *résultat*, pas le détail du code (il est dans
les messages de commit).

Pas d'entrée pour une synchro de config, une coquille, un renommage, un correctif
d'un seul fichier. En cas de doute : est-ce que quelqu'un qui revient dans six
semaines aurait besoin de lire ça ? Sinon, on n'écrit rien.

Court et simple. Une entrée se lit en une minute, et si une décision a un piège,
elle le nomme — une entrée qui ne dit que du bien est une entrée inutile.

<!--
Format d'une entrée — insérée en haut, juste sous cet en-tête :

## [AAAA-MM-JJ] — [une ligne : ce que ça change, pas ce que ça touche]

**Ce qu'on voulait**
[le problème, en clair. Ce qu'on ne pouvait pas faire avant.]

**Comment on a procédé**
[les étapes, dans l'ordre où elles ont eu lieu — pas la liste des fichiers.]

**Le résultat**
[ce qui est vrai maintenant et ne l'était pas. La preuve quand il y en a une.]

**Décisions à retenir**
[les choix qu'on ne veut pas rejouer dans six semaines, avec leur raison.
Omettre si aucun.]

**Différé, volontairement**
[ce qu'on a choisi de ne pas faire, et pourquoi. Omettre si rien.]

**Commits :** `abc1234`, `def5678`
-->

---

## 2026-11-04 — Des articles d'une votation aux comptes par entité Wikidata

**Ce qu'on voulait**
Le graphe média–acteur exige de savoir, article par article, qui est nommé et
combien de fois, avec *SVP* et *Schweizerische Volkspartei* sur un seul nœud. On
n'avait que des archives brutes. On a prototypé sur une tranche : DE seul, une
votation (A-631, Begrenzungsinitiative).

**Comment on a procédé**
Filtre regex sur le nom de l'initiative (1 086 articles), balisage vers texte,
label de pertinence par Haiku (473). spaCy, GLiNER et Haiku comparés sur les mêmes
articles ; seul Haiku continue, avec un balisage en ligne réaligné sur l'original.
Puis normalisation entre articles, résolution des noms vagues article par article,
liaison Wikidata (règle, puis Haiku, puis seconde recherche sous le nom officiel)
et fusion par QID. Une revue à la main a ensuite retiré 130 articles. Enfin le
calcul est passé du notebook 02 aux modules `preprocess`, `relevance`, `ner`,
`actors` et `linking`, avec les premiers tests du paquet.

**Le résultat**
343 articles, 9 139 mentions, 621 entités, 92,1 % des mentions sous un QID.
`entity_per_article` donne le compte par article, et un assert vérifie que les
sommes retombent sur les totaux. Les 9 partis de référence et Kurt Fluri sont
trouvés avec le bon QID ; Fässler et Piller Carrard sont à 0, ce qui est juste
pour ces articles. Après le passage en modules, les deux tables sont identiques à
une référence sauvée avant, sans aucun nouvel appel, et 35 tests passent.

**Décisions à retenir**
- Demander à Haiku une liste de noms puis la chercher dans le texte ne marche pas :
  toute graphie absente de la liste était perdue, surtout les noms de famille seuls.
  Remplacé par le balisage en ligne, à ne pas retenter.
- Le label de Haiku ne suffit pas. Il ne lit que le début de l'article, et les deux
  plus gros articles « related » étaient des tickers locaux, soit 8,4 % des
  mentions balisées. D'où `data/review/a631_relevance_review.csv`.
- Cette revue déplace la visibilité, et pas uniformément : SVP −19 %, FDP −41 %,
  CVP −49 %, SP −66 %. Retirer les articles sur l'accord-cadre (rang 4) est un
  jugement, et il pèse surtout sur le CVP. La méthode doit le dire.
- Une classe Wikidata (P279) n'est jamais un acteur, sinon *Stadtrat* fusionne les
  conseils de plusieurs villes. Un lieu sans siège n'est pas une organisation,
  sinon les Verts deviennent le hameau de Grünen.
- Pas de `maxlag` sur des lectures, et une réponse d'erreur n'est jamais mise en
  cache : 326 erreurs *too busy* passaient pour des recherches vides.
- Les prompts restent octet pour octet : ils font partie des clés de cache Haiku.

**Différé, volontairement**
Aucune mesure de précision : la vérification à la main du top 200 a été
abandonnée, et 222 articles ont été gardés sur leur seul titre. Les copies d'un
même texte entre médias comptent encore séparément. Ce code reste exploratoire,
limité à A-631, sans seed ni manifeste : rien n'en sort pour le rapport tel quel.
Le ton ciblé vient ensuite, sur une autre branche.

**Commits :** `8bac5c9`, `19bebd6`, `292f7ff`, `9d8a9dd`, `b6289bb`, `0394fb7`, `8442781`, `ca93b97`, `cb04cc6`

---

## 2026-09-14 — Le répertoire d'événements d'amorçage : 20 événements suisses, reproductibles, avec leurs acteurs en QID

**Ce qu'on voulait**
Un banc d'essai pour le liage d'entités interlingue, et un agenda contrôlé pour
comparer les médias entre eux. Sans ça, on ne peut ni mesurer si UDC et SVP
fusionnent correctement en un nœud, ni savoir si une différence entre deux
titres vient du média ou simplement du fait qu'ils ne couvraient pas la même
chose ce jour-là. La contrainte : aucune ligne écrite de mémoire, et un script
qui, relancé, retombe sur exactement le même jeu.

**Comment on a procédé**
Reconnaissance d'abord — quatre agents en parallèle, un par source, avec pour
seule mission de vérifier l'accès réel : format, endpoint, champs, volume.
Ensuite l'implémentation en séquentiel, prototype sur une seule votation avant
toute généralisation.

Swissvotes donne le bloc A. Les deux axes se calculent depuis le fichier :
polarisation depuis le partage de l'électorat entre les partis du oui et du non,
Röstigraben depuis l'écart de taux de oui entre cantons romands et alémaniques.
Wikidata fournit les blocs B, C et E, classés par nombre de versions
linguistiques Wikipédia. Curia Vista relie chaque objet de votation à des
personnes nommées, et `P1307` les transforme en QID sans jamais comparer une
chaîne de caractères.

**Le résultat**
20 événements — 8 votations, 4 élections du Conseil fédéral, 3 événements
suisses hors calendrier institutionnel, 1 contrôle consensuel, 4 internationaux
en diagnostic. 304 lignes d'entités sur 65 QID distincts, deux lignes par acteur
(une par langue), donc déjà la liste d'arêtes qu'attendra le graphe biparti.
20 requêtes Swissdox construites et validées contre l'API vivante, aucun article
téléchargé.

Deux runs consécutifs produisent des CSV identiques au byte près. C'était le
contrat ; il tient.

**Décisions à retenir**
L'exclusion des médias est passée d'un objet nommé à la main au **code de
domaine `12.5`**. Nommer le paquet d'aide aux médias ratait No-Billag, qui porte
le même code : les médias y sont partie prenante autant. Une règle mécanique a
attrapé ce qu'une liste manuelle manquait.

Le trou cantonal 2024 de Swissvotes a été rebouché (8 objets via les classeurs
OFS par objet, 2 via l'open data OFS). Ce n'était pas cosmétique : le vivier
passe de 46 à 56 objets, les médianes bougent, **et le bloc A change**. Sans ça
le jeu s'arrêtait de fait en mars 2024 sans que rien ne le dise.

La **porte temporelle** sur les partis règle d'un seul mécanisme ce qui aurait
été deux cas particuliers : la fusion PDC+PBD du 2021-01-01 et le renommage du
PLR de 2009. Wikidata n'a aucune conscience du temps — chercher « CVP »
aujourd'hui retourne un parti dissous, sans avertissement. La porte est à nous.

« Événements dominés par des acteurs étrangers » s'opérationnalise par `P710` :
le sommet Biden–Poutine de Genève sort, le rachat de Credit Suisse par UBS
reste. Le critère était dans la consigne ; il fallait le rendre calculable.

**Le piège à ne pas oublier**
Le 100 % de réconciliation est le **plafond d'une jointure par identifiant**, pas
une preuve que le liage fonctionne. Aucune ligne ne vient d'une forme de surface
trouvée dans du texte — c'est voulu, un corrigé construit par appariement flou
ne vaut rien. Le vrai test arrive avec les articles.

Trois événements ne portent **aucun** acteur de référence : Wikidata n'en nomme
pas. Ils gardent leur usage en comparaison à agenda contrôlé, ils perdent leur
usage comme cas de test. C'est signalé dans la table, pas rafistolé.

Et le constat structurel de la reconnaissance, qui dépasse ce lot : le côté
francophone de Swissdox n'est pas un espace médiatique francophone, c'est un
groupe de presse (TX Group) plus Le Temps et rts.ch. Le Nouvelliste, La Liberté,
ArcInfo, Le Courrier, Le Quotidien Jurassien sont absents du corpus, et il n'y a
aucune agence de presse. **Langue et propriétaire sont colinéaires par
construction** — à écrire dans le rapport comme une limite du corpus, pas à
découvrir dans six semaines comme un diagnostic.

**Le corpus, tiré ensuite**
Le volume ne pouvait pas se connaître avant de tirer : `estimateResults`
annonçait 574 pour une fenêtre qui en a rendu 87 403. Donc un pull d'étalonnage
d'abord, puis les autres. Total : **1 650 143 articles, 1,93 Go** sur 19
fenêtres — 19 et non 20, parce que deux objets votés le même jour partagent une
fenêtre, et les compter deux fois présenterait les mêmes articles comme deux
observations indépendantes.

Le tirage est **sans filtre de mots-clés**, volontairement. Sur la fenêtre
d'étalonnage, 1,7 % des articles mentionnent l'objet de la votation. Les 98 %
restants ne sont pas du déchet : ce sont le **dénominateur**. La visibilité est
une part d'attention, et une part sans dénominateur n'est qu'un décompte.

**Différé, volontairement**
La déduplication des quasi-doublons, et le liage d'entités sur texte réel. Le
notebook `notebooks/01_explore_the_data.ipynb` montre pourquoi les deux sont
indispensables : un scan regex naïf sur une fenêtre place les 16 titres
alémaniques en tête, le premier romand 17ᵉ. Soit la presse alémanique parle
vraiment plus des partis fédéraux, soit nos formes de surface allemandes
matchent mieux que les françaises. On ne peut pas trancher depuis ce graphique —
c'est précisément ce que le bloc E existe pour tester.

**Commits :** `1c64fbb`, `73167f6`, `ca54c3e`, `ef5f4ac`, `d9d2bbb`, `5a92f3c`, `bf69836`, `73dc55f`, `485a657`
