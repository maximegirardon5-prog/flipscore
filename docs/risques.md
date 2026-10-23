# Analyse des risques

> Ceci n'est pas un avis juridique ou fiscal. Pour une activité régulière, fais valider ta
> situation par un expert-comptable ou par l'URSSAF.

## 1. Juridique

### Conditions d'utilisation des plateformes

| Plateforme | Risque | Ce qu'on fait |
|---|---|---|
| **Leboncoin** | Les CGU interdisent l'extraction automatisée, et les annonces sont protégées par le **droit des bases de données** (droit « sui generis », Code de la propriété intellectuelle). Leboncoin a déjà fait condamner en justice des sites qui aspiraient ses annonces. Protection anti-robots (Datadome). | **Aucun scraping.** Saisie semi-manuelle (lien, texte, capture d'écran) et lecture de **tes propres e-mails d'alerte**. |
| **Vinted** | Même situation : CGU, anti-robots, risque de bannissement du compte. Les CGU réservent aussi les comptes particuliers aux non-professionnels. | Comme pour Leboncoin. |
| **eBay** | API officielle, mais soumise à la licence développeur (durée de conservation des données, usages autorisés, quotas). | Respect de la licence, conservation limitée et purge. À relire au moment de créer le connecteur (phase 2). |
| **Lien partagé** | Si le serveur télécharge lui-même la page Leboncoin ou Vinted, c'est un accès automatisé, même ponctuel, souvent bloqué. | **Décision à prendre en phase 2.** Ma recommandation : ne pas télécharger la page, et passer par une capture d'écran ou un texte collé. |

### Données personnelles (RGPD)

Les pseudos, villes et notes des vendeurs sont des données personnelles. Comme l'usage est
lucratif, l'exemption « usage purement personnel » est fragile. Mesures prises :
minimisation (pas de nom, téléphone ni e-mail), pseudonymisation par hachage, purge des
données brutes après 90 jours, aucune donnée acheteur, aucun partage, base privée.

### Recel et objets volés

Acheter un objet volé, même de bonne foi, peut poser problème (recel), surtout pour les
**smartphones** (vérifier l'IMEI et le verrou iCloud ou Google) et les **vélos** (marquage
Bicycode, facture). Ces vérifications seront intégrées au critère « risque » du score.

### Fiscalité et statut

- Vendre **tes propres affaires d'occasion** en tant que particulier est en principe non
  imposable.
- **Acheter pour revendre de façon régulière avec un objectif de profit est une activité
  commerciale**. Elle doit être déclarée (la micro-entreprise est le statut le plus simple)
  et les bénéfices sont imposables. Ne pas la déclarer expose à un redressement, voire à une
  qualification de travail dissimulé.
- Les plateformes transmettent au fisc les comptes qui dépassent certains seuils de ventes
  annuelles (directive européenne **DAC7** : à ce jour 30 ventes ou 2 000 € par an).
- L'application prévoit le champ `tax_rate_pct` (0 aujourd'hui) pour intégrer les
  cotisations dans la marge nette le jour où tu changes de statut.
- **Recommandation** : dès que l'activité devient régulière, crée une micro-entreprise et
  bascule sur les comptes professionnels des plateformes.

### Hébergement

L'offre gratuite de Vercel (Hobby) est réservée à un usage personnel et non commercial. Un
outil privé, utilisé par toi seul, est une zone grise à risque faible. Si l'activité devient
professionnelle ou si l'app est ouverte à d'autres, il faudra passer à une offre payante ou
à un serveur à toi.

## 2. Technique

| Risque | Impact | Parade |
|---|---|---|
| Changement du format des e-mails d'alerte Leboncoin ou Vinted | le connecteur e-mail ne lit plus rien | tests avec des e-mails d'exemple, alerte si 0 annonce lue pendant N jours |
| Évolution ou quotas de l'API eBay | collecte eBay interrompue | gestion d'erreur dédiée (`SourceTemporaryError`), journal `job_runs` |
| Les annonces actives eBay ne sont pas des prix de vente | estimation biaisée vers le haut | pondération par qualité, priorité à tes ventes réelles, niveau de confiance affiché |
| Retards de GitHub Actions (cron) | alertes en retard de quelques minutes | accepté ; le partage manuel au bot reste instantané |
| Mise en pause de Supabase après 7 jours sans activité | base inaccessible | tâche `heartbeat` quotidienne |
| Désactivation des crons GitHub après 60 jours sans activité | concerne les dépôts **publics** | dépôt **privé** |
| Limite de durée des fonctions Vercel | analyse IA trop longue | traitements lourds déplacés vers les tâches de fond |
| Offres gratuites modifiées par les fournisseurs | coût imprévu ou service coupé | code portable (PostgreSQL standard, commandes autonomes), plan B VPS |
| Différences SQLite / PostgreSQL | bug en production seulement | migration testée sur les deux ; tests d'intégration PostgreSQL à ajouter en CI |

## 3. Coûts

| Poste | Coût | Limite à surveiller |
|---|---|---|
| GitHub (dépôt privé) + Actions | 0 € | environ 2 000 min/mois d'Actions en privé |
| Codespaces | 0 € | environ 60 h/mois : arrêter le Codespace après usage |
| Vercel Hobby | 0 € | usage non commercial, limites de requêtes |
| Supabase | 0 € | 500 Mo de base : on stocke les liens des photos, pas les fichiers, et on purge |
| IA (palier gratuit, ex. Gemini) | 0 € | quotas journaliers ; **en gratuit, les données envoyées peuvent servir à entraîner les modèles du fournisseur** : n'envoyer que l'annonce, rien de personnel |
| Nom de domaine | ~10 €/an | optionnel |

Garde-fou : chaque appel IA passe par `BudgetGuard`, qui bloque tout appel payant au-delà
de `AI_MONTHLY_BUDGET_CENTS` (0 par défaut). L'application continue alors sans IA.
