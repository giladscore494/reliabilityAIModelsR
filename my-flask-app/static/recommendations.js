// =============================
//  Car Advisor – Frontend Logic
//  Works with recommendations.html
// =============================

// ---- שליטה על השלבים ----
let currentStep = 0;

function showStep(n) {
    document.querySelectorAll(".step").forEach((s) => s.classList.remove("active"));
    document.getElementById(`step${n}`).classList.add("active");
    currentStep = n;
}

function nextStep() {
    showStep(currentStep + 1);
}

function prevStep() {
    showStep(currentStep - 1);
}



// =============================
// איסוף כל הנתונים מהטופס
// =============================
function collectProfile() {
    const profile = {};

    // ---- שלב 1 ----
    profile.budget_min = parseFloat(document.getElementById("budget_min").value || 0);
    profile.budget_max = parseFloat(document.getElementById("budget_max").value || 0);

    profile.year_min = parseInt(document.getElementById("year_min").value || 2000);
    profile.year_max = parseInt(document.getElementById("year_max").value || 2025);

    profile.fuels_he = Array.from(document.getElementById("fuels").selectedOptions).map(o => o.value);
    profile.gears_he = Array.from(document.getElementById("gears").selectedOptions).map(o => o.value);
    profile.turbo_choice_he = document.getElementById("turbo").value;

    // ---- שלב 2 ----
    profile.main_use = document.getElementById("main_use").value;
    profile.annual_km = parseInt(document.getElementById("annual_km").value || 0);
    profile.driver_age = parseInt(document.getElementById("driver_age").value || 18);

    // ---- שלב 3 ----
    profile.weights = {
        reliability: parseInt(document.getElementById("weight_reliability").value),
        resale: parseInt(document.getElementById("weight_resale").value),
        fuel: parseInt(document.getElementById("weight_fuel").value),
        performance: parseInt(document.getElementById("weight_perf").value),
        comfort: parseInt(document.getElementById("weight_comfort").value),
    };

    // ---- שלב 4 ----
    profile.fuel_price = parseFloat(document.getElementById("fuel_price").value || 7);
    profile.electricity_price = parseFloat(document.getElementById("electricity_price").value || 0.65);

    return profile;
}



// =============================
// שליחת הפרופיל לשרת (Flask)
// =============================
async function sendProfile() {
    const profile = collectProfile();

    // הצגת סטטוס טעינה
    const loadingEl = document.getElementById("loading");
    const resultsEl = document.getElementById("results");
    loadingEl.classList.remove("hidden");
    resultsEl.innerHTML = "";

    try {
        const resp = await fetch("/advisor_api", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(profile)
        });

        const json = await resp.json();
        loadingEl.classList.add("hidden");

        if (!resp.ok) {
            resultsEl.innerHTML = `
                <div class="text-red-400 text-xl mt-4">שגיאה: ${json.error || "תקלה לא ידועה"}</div>
            `;
            return;
        }

        renderResults(json);

    } catch (err) {
        loadingEl.classList.add("hidden");
        resultsEl.innerHTML = `
            <div class="text-red-400 text-xl mt-4">שגיאת רשת: ${err}</div>
        `;
    }
}



// =============================
// הצגת התוצאות
// =============================
function renderResults(data) {
    const el = document.getElementById("results");

    if (!data || !data.recommended_cars) {
        el.innerHTML = `<div class="text-red-400 text-xl">לא התקבלו תוצאות.</div>`;
        return;
    }

    let html = `
        <h3 class="text-2xl font-bold mb-4 text-indigo-300">תוצאות ההמלצות</h3>
        <p class="text-sm opacity-70 mb-4">סה״כ ${data.recommended_cars.length} רכבים מתאימים</p>
    `;

    data.recommended_cars.forEach((car, idx) => {
        html += `
        <div class="card p-4 rounded-xl mb-4">
            <h4 class="text-xl font-bold text-indigo-400 mb-2">
                ${idx + 1}. ${car.brand} ${car.model} ${car.year}
            </h4>

            <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm opacity-80">
                <div>דלק: ${car.fuel}</div>
                <div>תיבה: ${car.gear}</div>
                <div>טורבו: ${car.turbo}</div>
                <div>אמינות: ${car.reliability_score}/10</div>
                <div>אחזקה: ${car.maintenance_cost} ₪/שנה</div>
                <div>ביטוח: ${car.insurance_cost} ₪</div>
                <div>עלות שנתית: ${car.total_annual_cost} ₪</div>
                <div>התאמה: ${car.suitability}/10</div>
            </div>

            <p class="mt-3 text-sm">${car.comparison_comment || ""}</p>
        </div>
        `;
    });

    el.innerHTML = html;
}



// =============================
// הפעלה ראשונית
// =============================
showStep(0);
