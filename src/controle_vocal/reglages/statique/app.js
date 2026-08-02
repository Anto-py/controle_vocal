/* Interface de réglages : liste des profils à gauche, table des commandes à droite.
 *
 * La page ne valide rien elle-même. Le serveur seul dit oui ou non, avec les
 * mêmes contrôles que le lancement : une page qui aurait sa propre idée de ce
 * qui est valide finirait par diverger du coeur, et c'est le coeur qui a le
 * dernier mot devant le public.
 */

const COLONNES = ["application", "bundle_id", "commande", "touches", "phrases", "actif"];

const etat = {
  profil: null,
  lignes: [],
  touches: { touches: [], modificateurs: [], actions: [] },
  moteur: { actif: false },
};

/* Rythme de relecture de l'état de la télécommande. Deux secondes suffisent :
 * l'interrupteur doit surtout dire la vérité quand l'outil s'est arrêté tout
 * seul, micro débranché ou « extinction » dite à la voix. */
const PERIODE_ETAT = 2000;

const $ = (id) => document.getElementById(id);

// --- Accès au serveur -------------------------------------------------------

async function demander(route, options = {}) {
  const reponse = await fetch(route, options);
  const type = reponse.headers.get("Content-Type") || "";
  const charge = type.includes("json") ? await reponse.json() : await reponse.text();
  return { ok: reponse.ok, code: reponse.status, charge };
}

// --- Rendu ------------------------------------------------------------------

function rendreListeProfils(profils) {
  const liste = $("liste-profils");
  liste.replaceChildren();
  for (const profil of profils) {
    const element = document.createElement("li");
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "profil-bouton" + (profil.erreur ? " casse" : "");
    bouton.setAttribute("aria-current", String(profil.nom === etat.profil));

    const nom = document.createElement("span");
    nom.className = "profil-nom";
    nom.textContent = profil.nom;

    const detail = document.createElement("span");
    detail.className = "profil-detail";
    detail.textContent = profil.erreur
      ? "fichier illisible"
      : `${profil.application || "sans nom"} · ${profil.commandes} active${profil.commandes > 1 ? "s" : ""}`;

    bouton.append(nom, detail);
    bouton.addEventListener("click", () => ouvrirProfil(profil.nom));
    element.append(bouton);
    liste.append(element);
  }
}

function champ(ligne, colonne, index, options = {}) {
  const entree = document.createElement("input");
  entree.className = "retro-input";
  entree.type = "text";
  entree.value = ligne[colonne] ?? "";
  entree.dataset.colonne = colonne;
  entree.setAttribute("aria-label", options.etiquette || colonne);
  if (options.liste) entree.setAttribute("list", options.liste);
  if (options.disabled) entree.disabled = true;
  entree.addEventListener("input", () => {
    etat.lignes[index][colonne] = entree.value;
  });
  return entree;
}

function rendreTable() {
  const corps = $("corps-table");
  corps.replaceChildren();

  etat.lignes.forEach((ligne, index) => {
    const interne = (ligne.touches || "").startsWith("@");
    const rangee = document.createElement("tr");
    rangee.className = interne ? "interne" : "";
    rangee.dataset.index = String(index);

    const celluleActif = document.createElement("td");
    const case_ = document.createElement("input");
    case_.type = "checkbox";
    case_.className = "case-actif";
    case_.checked = ["oui", "o", "vrai", "1", "true"].includes(
      (ligne.actif || "").trim().toLowerCase(),
    );
    case_.setAttribute("aria-label", `Activer ${ligne.commande || "cette commande"}`);
    case_.addEventListener("change", () => {
      etat.lignes[index].actif = case_.checked ? "oui" : "non";
    });
    celluleActif.append(case_);

    const celluleNom = document.createElement("td");
    celluleNom.append(champ(ligne, "commande", index, { etiquette: "Nom de la commande" }));

    const celluleTouches = document.createElement("td");
    celluleTouches.append(
      champ(ligne, "touches", index, {
        etiquette: "Touches à envoyer",
        liste: "touches-connues",
      }),
    );

    const cellulePhrases = document.createElement("td");
    cellulePhrases.append(
      champ(ligne, "phrases", index, { etiquette: "Formulations, séparées par |" }),
    );

    const celluleSuppression = document.createElement("td");
    const supprimer = document.createElement("button");
    supprimer.type = "button";
    supprimer.className = "supprimer";
    supprimer.textContent = "✕";
    supprimer.title = interne
      ? "Les actions internes se désactivent, elles ne se suppriment pas"
      : "Supprimer la ligne";
    supprimer.setAttribute("aria-label", `Supprimer ${ligne.commande || "la ligne"}`);
    supprimer.disabled = interne;
    supprimer.addEventListener("click", () => {
      etat.lignes.splice(index, 1);
      rendreTable();
    });
    celluleSuppression.append(supprimer);

    rangee.append(celluleActif, celluleNom, celluleTouches, cellulePhrases, celluleSuppression);
    corps.append(rangee);
  });
}

function rendreTouchesConnues() {
  let liste = document.getElementById("touches-connues");
  if (!liste) {
    liste = document.createElement("datalist");
    liste.id = "touches-connues";
    document.body.append(liste);
  }
  const valeurs = [...etat.touches.touches, ...(etat.touches.actions || [])];
  liste.replaceChildren(
    ...valeurs.map((valeur) => {
      const option = document.createElement("option");
      option.value = valeur;
      return option;
    }),
  );
}

function afficherBandeau(classe, titre, details = []) {
  const bandeau = $("bandeau");
  bandeau.className = `bandeau ${classe}`;
  bandeau.replaceChildren();

  const paragraphe = document.createElement("p");
  paragraphe.textContent = titre;
  bandeau.append(paragraphe);

  if (details.length) {
    const liste = document.createElement("ul");
    for (const detail of details) {
      const item = document.createElement("li");
      item.textContent = detail;
      liste.append(item);
    }
    bandeau.append(liste);
  }
  bandeau.hidden = false;
}

function marquerRefus(refus) {
  document.querySelectorAll(".fautive").forEach((r) => r.classList.remove("fautive"));
  document.querySelectorAll(".retro-input.error").forEach((c) => c.classList.remove("error"));
  document.querySelectorAll(".refus-ligne").forEach((n) => n.remove());

  for (const r of refus) {
    // La ligne 2 du fichier est la première ligne de données.
    const rangee = document.querySelector(`tr[data-index="${r.ligne - 2}"]`);
    if (!rangee) continue;
    rangee.classList.add("fautive");
    const cellule = rangee.querySelector(`[data-colonne="${r.colonne}"]`);
    if (cellule) {
      cellule.classList.add("error");
      const note = document.createElement("span");
      note.className = "refus-ligne";
      note.textContent = r.message;
      cellule.parentElement.append(note);
    }
  }
}

// --- La télécommande, marche et arrêt ---------------------------------------

function rendreMoteur(moteur) {
  etat.moteur = moteur;
  const bouton = $("interrupteur");
  bouton.setAttribute("aria-pressed", String(moteur.actif));
  bouton.disabled = false;
  bouton.querySelector(".interrupteur-action").textContent = moteur.actif
    ? "Arrêter"
    : "Mettre en marche";

  const detail = [];
  if (moteur.actif) {
    detail.push("en marche");
    if (moteur.options?.profil) detail.push(`profil ${moteur.options.profil}`);
    else detail.push("profil automatique");
    if (moteur.options?.pastille) detail.push("pastille allumée");
  } else if (moteur.code_retour !== null && moteur.code_retour !== undefined) {
    detail.push(moteur.code_retour === 0 ? "arrêtée" : `arrêtée (code ${moteur.code_retour})`);
  } else {
    detail.push("arrêtée");
  }
  $("etat-moteur").textContent = detail.join(" · ");

  $("option-profil").disabled = moteur.actif;
  $("option-pastille").disabled = moteur.actif;

  const journal = $("journal-moteur");
  const lignes = moteur.journal || [];
  journal.hidden = lignes.length === 0;
  journal.textContent = lignes.join("\n");
  journal.scrollTop = journal.scrollHeight;
}

async function relireMoteur() {
  const { ok, charge } = await demander("/api/moteur");
  if (ok) rendreMoteur(charge);
}

async function basculerMoteur() {
  const bouton = $("interrupteur");
  bouton.disabled = true;

  const arret = etat.moteur.actif;
  const options = arret
    ? {}
    : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profil: $("option-profil").value || null,
          pastille: $("option-pastille").checked,
        }),
      };
  const route = arret ? "/api/moteur/arreter" : "/api/moteur/demarrer";
  const { ok, charge } = await demander(route, arret ? { method: "POST" } : options);

  if (!ok) {
    afficherBandeau("echec", arret ? "Arrêt impossible." : "Lancement impossible.", [
      charge.erreur || "",
    ]);
    return relireMoteur();
  }
  rendreMoteur(charge);
  $("bandeau").hidden = true;

  // Un échec au lancement (micro absent, modèle manquant) se voit à la seconde
  // suivante, pas à l'instant du clic : le processus a le temps de mourir.
  if (!arret) setTimeout(relireMoteur, 1200);
}

// --- L'autorisation macOS ---------------------------------------------------

/* Elle est affichée en permanence, accordée ou non. Une autorisation qui marche
 * sans que l'application figure dans le panneau des Réglages système est une
 * autorisation empruntée à un autre maillon de la chaîne, qui tombera le jour où
 * celui-ci changera de version. Mieux vaut la voir que la découvrir en séance. */

async function relireAutorisation() {
  const { ok, charge } = await demander("/api/accessibilite");
  const bloc = $("autorisation");
  if (!ok) {
    bloc.hidden = true;
    return;
  }
  bloc.hidden = false;
  bloc.classList.toggle("manquante", !charge.accordee);
  $("autorisation-texte").textContent = charge.accordee
    ? "Autorisation Accessibilité accordée : les touches peuvent partir."
    : "Autorisation Accessibilité absente : la télécommande démarrera, mais aucune touche ne partira.";
  $("autorisation-demander").hidden = charge.accordee;
}

async function demanderAutorisation() {
  await demander("/api/accessibilite/demander", { method: "POST" });
  afficherBandeau(
    "echec",
    "Autorisation demandée au système.",
    [
      "Cocher « Contrôle vocal » dans Réglages système, Confidentialité et sécurité, Accessibilité.",
      "Puis fermer et rouvrir l'application : l'autorisation n'est lue qu'au lancement.",
    ],
  );
  setTimeout(relireAutorisation, 1000);
}

async function fermerReglages() {
  const arret = etat.moteur.actif
    ? "La télécommande sera arrêtée avec les réglages. Fermer ?"
    : "Fermer les réglages ?";
  if (!window.confirm(arret)) return;

  // La réponse n'arrivera peut-être pas : le serveur se ferme en la disant. Un
  // échec de requête est donc ici le signe que ça a marché.
  try {
    await demander("/api/quitter", { method: "POST" });
  } catch (erreur) {
    void erreur;
  }
  document.body.replaceChildren(messageDeFermeture());
}

function messageDeFermeture() {
  const bloc = document.createElement("main");
  bloc.className = "page-frame ferme";
  const titre = document.createElement("h1");
  titre.textContent = "Réglages fermés";
  const note = document.createElement("p");
  note.textContent =
    "Cette page peut être fermée. Rouvrir l'application pour revenir.";
  bloc.append(titre, note);
  return bloc;
}

function remplirChoixProfils(profils) {
  const choix = $("option-profil");
  const retenu = choix.value;
  choix.replaceChildren();
  const automatique = document.createElement("option");
  automatique.value = "";
  automatique.textContent = "Suit l'application au premier plan";
  choix.append(automatique);
  for (const profil of profils) {
    if (profil.erreur) continue;
    const option = document.createElement("option");
    option.value = profil.nom;
    option.textContent = profil.nom;
    choix.append(option);
  }
  choix.value = retenu;
}

// --- Actions ----------------------------------------------------------------

async function chargerListe() {
  const { ok, charge } = await demander("/api/profils");
  if (!ok) return afficherBandeau("echec", "Liste des profils illisible.");
  rendreListeProfils(charge.profils);
  remplirChoixProfils(charge.profils);
  if (!etat.profil && charge.profils.length) {
    await ouvrirProfil(charge.profils[0].nom);
  }
}

async function ouvrirProfil(nom) {
  const { ok, charge } = await demander(`/api/profils/${nom}`);
  if (!ok) {
    return afficherBandeau("echec", `Profil « ${nom} » illisible.`, [charge.erreur || ""]);
  }
  etat.profil = nom;
  etat.lignes = charge.lignes;
  $("titre-profil").textContent = nom;
  const application = charge.lignes.find((l) => l.application)?.application || "";
  const bundle = charge.lignes.find((l) => l.bundle_id)?.bundle_id || "aucun identifiant";
  $("sous-titre-profil").textContent = `${application} · ${bundle}`;
  $("lien-export").href = `/api/profils/${nom}/export`;
  $("lien-export").setAttribute("download", `${nom}.csv`);
  $("bandeau").hidden = true;
  rendreTable();
  await chargerListe();
}

async function enregistrer() {
  const { ok, charge } = await demander(`/api/profils/${etat.profil}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lignes: etat.lignes }),
  });

  if (ok) {
    marquerRefus([]);
    afficherBandeau("succes", `Profil « ${etat.profil} » enregistré.`, [
      "L'outil relit ses profils à chaque changement d'application : rien à redémarrer.",
    ]);
    return chargerListe();
  }

  const refus = charge.refus || [{ ligne: 0, colonne: "", message: charge.erreur }];
  marquerRefus(refus);
  afficherBandeau(
    "echec",
    "Rien n'a été écrit, le fichier est intact.",
    refus.map((r) => (r.ligne ? `Ligne ${r.ligne} : ${r.message}` : r.message)),
  );
}

function ajouterLigne() {
  const modele = etat.lignes.find((l) => l.application) || {};
  const vide = Object.fromEntries(COLONNES.map((colonne) => [colonne, ""]));
  etat.lignes.push({
    ...vide,
    application: modele.application || "",
    bundle_id: modele.bundle_id || "",
    actif: "oui",
  });
  rendreTable();
  const dernier = document.querySelector('tr:last-child [data-colonne="commande"]');
  if (dernier) dernier.focus();
}

async function importer(fichier) {
  const texte = await fichier.text();
  const { ok, charge } = await demander(`/api/profils/${etat.profil}/import`, {
    method: "POST",
    headers: { "Content-Type": "text/csv" },
    body: texte,
  });
  if (ok) {
    afficherBandeau("succes", `« ${fichier.name} » importé dans « ${etat.profil} ».`);
    return ouvrirProfil(etat.profil);
  }
  const refus = charge.refus || [{ ligne: 0, message: charge.erreur }];
  afficherBandeau(
    "echec",
    "Import refusé, le profil est intact.",
    refus.map((r) => (r.ligne ? `Ligne ${r.ligne} : ${r.message}` : r.message)),
  );
}

// --- Amorçage ---------------------------------------------------------------

async function demarrer() {
  const { ok, charge } = await demander("/api/touches");
  if (ok) etat.touches = charge;
  rendreTouchesConnues();

  $("enregistrer").addEventListener("click", enregistrer);
  $("ajouter").addEventListener("click", ajouterLigne);
  $("interrupteur").addEventListener("click", basculerMoteur);
  $("fermer").addEventListener("click", fermerReglages);
  $("autorisation-demander").addEventListener("click", demanderAutorisation);
  $("import").addEventListener("change", (evenement) => {
    const [fichier] = evenement.target.files;
    if (fichier) importer(fichier);
    evenement.target.value = "";
  });

  await chargerListe();
  await relireMoteur();
  await relireAutorisation();
  setInterval(relireMoteur, PERIODE_ETAT);
}

demarrer();
