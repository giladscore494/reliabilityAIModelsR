// =============================
//  Car Advisor – Frontend Logic
//  עובד עם recommendations.html
// =============================

// ---- שליטה על השלבים ----
let currentStep = 0;

function showStep(n) {
    document.querySelectorAll(".step").forEach((s) => s.classList.remove("active"));
    const target = document.getElementById(`step${n}`);
    if (target) {
        target.classList.add("active");
        currentStep = n;
    }
}

function nextStep() {
    showStep(currentStep + 1);
}

function prevStep() {
    showStep(currentStep - 1);
}

// =============================
// עזר קטן לשליפת ערכים
// =============================
function getValue(id, fallback = "") {
    const el = document.getElementById(id);
    if (!el) return fallback;
    if (el.type === "number") {
        const v = parseFloat(el.value);
        return isNaN(v) ? fallback : v;
    }
    return el.value !== undefined && el.value !== null && el.value !== "" ? el.value : fallback;
}

function getMultiSelect(id) {
    const el = document.getElementById(id);
    if (!el) return [];
    return Array.from(el.selectedOptions).map(o => o.value);
}

function getRadioValue(name, fallback = "") {
    const el = document.querySelector(`input[name="${name}"]:checked`);
    return el ? el.value : fallback;
}

// =============================
// איסוף כל הנתונים מהטופס – לפי ה־Streamlit המקורי
// =============================
function collectProfile() {
    const profile = {};

    // ---- שלב 1: פרטים בסיסיים ----
    profile.budget_min = parseFloat(getValue("budget_min", 0));
    profile.budget_max = parseFloat(getValue("budget_max", 0));

    profile.year_min = parseInt(getValue("year_min", 2000));
    profile.year_max = parseInt(getValue("year_max", 2025));

    profile.fuels_he = getMultiSelect("fuels");      // ערכים בעברית, כמו Streamlit
    profile.gears_he = getMultiSelect("gears");      // ערכים בעברית
    profile.turbo_choice_he = getValue("turbo", "לא משנה");

    // ---- שלב 2: שימוש וסגנון ----
    profile.main_use = getValue("main_use", "");
    profile.annual_km = parseInt(getValue("annual_km", 0));
    profile.driver_age = parseInt(getValue("driver_age", 18));

    profile.license_years = parseInt(getValue("license_years", 0));
    profile.driver_gender = getValue("driver_gender", "זכר");

    profile.body_style = getValue("body_style", "כללי");
    profile.driving_style = getValue("driving_style", "רגוע ונינוח");
    profile.seats_choice = getValue("seats_choice", "5");

    const excludedColorsRaw = getValue("excluded_colors", "");
    profile.excluded_colors = excludedColorsRaw
        .split(",")
        .map(s => s.trim())
        .filter(Boolean);

    // ---- שלב 3: סדר עדיפויות ----
    profile.weights = {
        reliability: parseInt(getValue("weight_reliability", 5)),
        resale: parseInt(getValue("weight_resale", 3)),
        fuel: parseInt(getValue("weight_fuel", 4)),
        performance: parseInt(getValue("weight_perf", 2)),
        comfort: parseInt(getValue("weight_comfort", 3)),
    };

    // ---- שלב 4: פרטים נוספים ----
    profile.insurance_history = getValue("insurance_history", "");
    profile.violations = getValue("violations", "אין");

    profile.family_size = getValue("family_size", "1-2");
    profile.cargo_need = getValue("cargo_need", "בינוני");

    // תלוי אם בנוי כ-radio או select – תומך בשניהם
    const safetyFromRadio = getRadioValue("safety_required", "");
    profile.safety_required = safetyFromRadio || getValue("safety_required", "כן");

    profile.trim_level = getValue("trim_level", "סטנדרטי");

    const supplyFromRadio = getRadioValue("consider_supply", "");
    profile.consider_supply = supplyFromRadio || getValue("consider_supply", "כן");

    profile.fuel_price = parseFloat(getValue("fuel_price", 7));
    profile.electricity_price = parseFloat(getValue("electricity_price", 0.65));

    return profile;
}

// =============================
// שליחת הפרופיל לשרת (Flask)
// =============================
async function sendProfile() {
    const profile = collectProfile();

    const loadingEl = document.getElementById("loading");
    const resultsEl = document.getElementById("results");

    if (loadingEl) loadingEl.classList.remove("hidden");
    if (resultsEl) resultsEl.innerHTML = "";

    try {
        const resp = await fetch("/advisor_api", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(profile),
        });

        const json = await resp.json();
        if (loadingEl) loadingEl.classList.add("hidden");

        if (!resp.ok) {
            if (resultsEl) {
                resultsEl.innerHTML = `
                    <div class="text-red-400 text-xl mt-4">
                        שגיאה: ${json.error || "תקלה לא ידועה"}
                    </div>
                `;
            }
            return;
        }

        renderResults(json);

    } catch (err) {
        if (loadingEl) loadingEl.classList.add("hidden");
        if (resultsEl) {
            resultsEl.innerHTML = `
                <div class="text-red-400 text-xl mt-4">
                    שגיאת רשת: ${err}
                </div>
            `;
        }
    }
}

// =============================
// הצגת התוצאות
// =============================
function renderResults(data) {
    const el = document.getElementById("results");
    if (!el) return;

    if (!data || !Array.isArray(data.recommended_cars)) {
        el.innerHTML = `<div class="text-red-400 text-xl">לא התקבלו תוצאות.</div>`;
        return;
    }

    const cars = data.recommended_cars;
    let html = `
        <h3 class="text-2xl font-bold mb-4 text-indigo-300">תוצאות ההמלצות</h3>
        <p class="text-sm opacity-70 mb-4">סה״כ ${cars.length} רכבים מתאימים</p>
    `;

    cars.forEach((car, idx) => {
        const fitScore = car.fit_score !== undefined && car.fit_score !== null
            ? `${car.fit_score}/100`
            : "לא זמין";

        const totalAnnual = car.total_annual_cost !== undefined && car.total_annual_cost !== null
            ? `${car.total_annual_cost} ₪`
            : "לא זמין";

        const priceRange = car.price_range_nis || "";
        const marketSupply = car.market_supply || "";

        html += `
        <div class="card p-4 rounded-xl mb-4">
            <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-2 mb-2">
                <h4 class="text-xl font-bold text-indigo-400">
                    ${idx + 1}. ${car.brand || ""} ${car.model || ""} ${car.year || ""}
                </h4>
                <div class="flex flex-wrap gap-2 text-xs">
                    <span class="px-3 py-1 rounded-full bg-slate-800/70 border border-slate-600">
                        ציון התאמה: <strong>${fitScore}</strong>
                    </span>
                    ${marketSupply
                        ? `<span class="px-3 py-1 rounded-full bg-slate-800/70 border border-slate-600">
                               היצע בשוק: ${marketSupply}
                           </span>`
                        : ""
                    }
                </div>
            </div>

            ${priceRange
                ? `<p class="text-sm opacity-80 mb-2">טווח מחיר משוער: ${priceRange}</p>`
                : ""
            }

            <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm opacity-80">
                <div>דלק: ${car.fuel || "-"}</div>
                <div>תיבה: ${car.gear || "-"}</div>
                <div>טורבו: ${car.turbo !== undefined ? car.turbo : "-"}</div>
                <div>אמינות: ${car.reliability_score !== undefined ? car.reliability_score + "/10" : "-"}</div>
                <div>אחזקה: ${car.maintenance_cost !== undefined ? car.maintenance_cost + " ₪/שנה" : "-"}</div>
                <div>ביטוח: ${car.insurance_cost !== undefined ? car.insurance_cost + " ₪/שנה" : "-"}</div>
                <div>עלות שנתית כוללת: ${totalAnnual}</div>
                <div>נוחות: ${car.comfort_features !== undefined ? car.comfort_features + "/10" : "-"}</div>
                <div>בטיחות: ${car.safety_rating !== undefined ? car.safety_rating + "/10" : "-"}</div>
                <div>שמירת ערך: ${car.resale_value !== undefined ? car.resale_value + "/10" : "-"}</div>
                <div>ביצועים: ${car.performance_score !== undefined ? car.performance_score + "/10" : "-"}</div>
                <div>התאמה כללית: ${car.suitability !== undefined ? car.suitability + "/10" : "-"}</div>
            </div>

            ${car.comparison_comment
                ? `<p class="mt-3 text-sm">${car.comparison_comment}</p>`
                : ""
            }

            ${car.not_recommended_reason
                ? `<p class="mt-2 text-xs text-amber-300">⚠️ הערת זהירות: ${car.not_recommended_reason}</p>`
                : ""
            }
        </div>
        `;
    });

    el.innerHTML = html;
}

// =============================
// הפעלה ראשונית
// =============================
showStep(0);
