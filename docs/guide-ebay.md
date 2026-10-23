# Guide : activer le connecteur eBay

Le connecteur est prêt mais **en sommeil** tant que les clés ne sont pas saisies. À faire quand
tu en as le temps (environ 20 minutes, plus le délai de validation d'eBay).

> ⚠️ Ne colle jamais une clé dans un chat, un e-mail ou un fichier du dépôt. Elles se saisissent
> uniquement dans les « Secrets » de GitHub (et dans `.env` sur ta machine si tu testes en local).

## 1. Créer le compte développeur

1. Va sur **developer.ebay.com** → **Register**.
2. Type de compte : **Individual**. Utilise ton Gmail dédié.
3. Valide l'e-mail de confirmation. La validation du compte peut prendre jusqu'à un jour ouvré.

## 2. Créer les clés de production

1. Connecte-toi, menu **Hi [ton nom]** → **Application Keysets**.
2. Donne un nom à l'application (ex. `flipscore`) puis, dans la colonne **Production**, clique
   **Create a keyset**.
3. eBay demande de traiter les notifications de **Marketplace Account Deletion**. Choisis
   l'option d'**exemption** (« I do not persist eBay data » / « Not persisting eBay data »).
   Motif à indiquer, en anglais :
   > *This is a private, single-user tool. It does not store any eBay user personal data:
   > seller usernames are removed before storage and only an irreversible hash is kept.*
4. Une fois l'exemption acceptée, la colonne **Production** affiche trois valeurs : **App ID
   (Client ID)**, **Dev ID**, **Cert ID (Client Secret)**. On a besoin de l'**App ID** et du
   **Cert ID**.

## 3. Saisir les clés dans GitHub

1. Sur la page du dépôt GitHub : **Settings** → **Secrets and variables** → **Actions**.
2. **New repository secret** :
   - Name `EBAY_CLIENT_ID` → Secret : l'App ID ;
   - Name `EBAY_CLIENT_SECRET` → Secret : le Cert ID.
3. C'est tout : au passage suivant de la collecte, les recherches de `config/searches.yaml` qui
   utilisent `ebay_api` commencent à remonter des annonces.

## 4. Vérifier

Onglet **Actions** → workflow **Collect** → dernière exécution : les lignes `ebay_api` passent
de ⏭️ (non configurée) à ✅ avec un nombre d'annonces.
