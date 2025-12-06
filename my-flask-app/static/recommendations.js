// /static/recommendations.js
// לוגיקת צד לקוח למנוע ההמלצות (Car Advisor / Gemini 3)

(function () {
    const form = document.getElementById('advisor-form');
    const submitBtn = document.getElementById('advisor-submit');
    const resultsSection = document.getElementById('advisor-results');
    const queriesEl = document.getElementById('advisor-search-queries');
    const tableWrapper = document.getElementById('advisor-table-wrapper');
    const errorEl = document.getElementById('advisor-error');
    const consentCheckbox = document.getElementById('advisor-consent');

    const profileSummaryEl = document.getElementById('advisor-profile-summary');
    const highlightCardsEl = document.getElementById('advisor-highlight-cards');

    if (!form) return;

    function setSubmitting(isSubmitting) {
        if (!submitBtn) return;
        const spinner = submitBtn.querySelector('.spinner');
        const textSpan = submitBtn.querySelector('.button-text');
        submitBtn.disabled = isSubmitting;
        if (spinner) spinner.classList.toggle('hidden', !isSubmitting);
        if (textSpan) textSpan.classList.toggle('opacity-60', isSubmitting);
    }

    function getCheckedValues(name) {
        return Array.from(form.querySelectorAll(`input[name="${name}"]:checked`)).map(el => el.value);
    }

    function getRadioValue(name, fallback) {
        const el = form.querySelector(`input[name="${name}"]:checked`);
        return el ? el.value : fallback;
    }

    function buildPayload() {
        const fuels_he = getCheckedValues('fuels_he');
        const gears_he = getCheckedValues('gears_he');
        const turbo_choice_he = getRadioValue('turbo_choice_he', 'לא משנה');
        const safety_required_radio = getRadioValue('safety_required_radio', 'כן');
        const consider_supply = getRadioValue('consider_supply', 'כן');

        const payload = {
            budget_min: parseFloat(form.budget_min.value || '0'),
            budget_max: parseFloat(form.budget_max.value || '0'),
            year_min: parseInt(form.year_min.value || '2000', 10),
            year_max: parseInt(form.year_max.value || '2025', 10),

            fuels_he,
            gears_he,
            turbo_choice_he,

            main_use: form.main_use.value || '',
            annual_km: parseInt(form.annual_km.value || '15000', 10),
            driver_age: parseInt(form.driver_age.value || '21', 10),
            license_years: parseInt(form.license_years.value || '0', 10),

            driver_gender: form.driver_gender.value || 'זכר',
            body_style: form.body_style.value || 'כללי',
            driving_style: form.driving_style.value || 'רגוע ונינוח',
            seats_choice: form.seats_choice.value || '5',

            family_size: form.family_size.value || '1-2',
            cargo_need: form.cargo_need.value || 'בינוני',

            insurance_history: form.insurance_history.value || '',
            violations: form.violations.value || 'אין',

            safety_required_radio,
            trim_level: form.trim_level.value || 'סטנדרטי',

            consider_supply,
            fuel_price: parseFloat(form.fuel_price.value || '7.0'),
            electricity_price: parseFloat(form.electricity_price.value || '0.65'),

            excluded_colors: form.excluded_colors.value || '',

            // משקלים
            weights: {
                reliability: parseInt(document.getElementById('w_reliability').value || '5', 10),
                resale: parseInt(document.getElementById('w_resale').value || '3', 10),
                fuel: parseInt(document.getElementById('w_fuel').value || '4', 10),
                performance: parseInt(document.getElementById('w_performance').value || '2', 10),
                comfort: parseInt(document.getElementById('w_comfort').value || '3', 10)
            }
        };

        return payload;
    }

    function formatPriceRange(range) {
        if (!range) return '';
        if (Array.isArray(range)) {
            if (range.length === 2) return `${range[0]}–${range[1]} ₪`;
            return range.join(' / ');
        }
        return String(range);
    }

    function safeNum(val, decimals = 0) {
        const n = Number(val);
        if (Number.isNaN(n)) return '';
        return n.toFixed(decimals);
    }

    // --- סיכום פרופיל משתמש אחרי קבלת התוצאות ---
    function renderProfileSummary() {
        if (!profileSummaryEl) return;

        const budgetMin = form.budget_min.value ? parseInt(form.budget_min.value, 10).toLocaleString('he-IL') + ' ₪' : 'לא צוין';
        const budgetMax = form.budget_max.value ? parseInt(form.budget_max.value, 10).toLocaleString('he-IL') + ' ₪' : 'לא צוין';
        const yearMin = form.year_min.value || 'לא צוין';
        const yearMax = form.year_max.value || 'לא צוין';

        const driverAge = form.driver_age.value || 'לא צוין';
        const licenseYears = form.license_years.value || 'לא צוין';
        const annualKm = form.annual_km.value ? parseInt(form.annual_km.value, 10).toLocaleString('he-IL') + ' ק״מ' : 'לא צוין';

        const mainUse = form.main_use.value || 'לא צוין שימוש עיקרי';
        const familySize = form.family_size.value || 'לא צוין';
        const seats = form.seats_choice.value || 'לא צוין';

        const fuels = getCheckedValues('fuels_he');
        const gears = getCheckedValues('gears_he');
        const drivingStyle = form.driving_style.value || 'לא צוין';
        const bodyStyle = form.body_style.value || 'כללי';

        const wReliability = document.getElementById('w_reliability')?.value || '5';
        const wFuel = document.getElementById('w_fuel')?.value || '4';
        const wResale = document.getElementById('w_resale')?.value || '3';
        const wPerf = document.getElementById('w_performance')?.value || '2';
        const wComfort = document.getElementById('w_comfort')?.value || '3';

        profileSummaryEl.innerHTML = `
            <div class="flex flex-wrap gap-2 mb-2">
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-800 text-[11px] text-slate-100 border border-slate-700">
                    תקציב: ${budgetMin} – ${budgetMax}
                </span>
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-800 text-[11px] text-slate-100 border border-slate-700">
                    שנים: ${yearMin}–${yearMax}
                </span>
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-800 text-[11px] text-slate-100 border border-slate-700">
                    ק״מ שנתי: ${annualKm}
                </span>
            </div>

            <div class="flex flex-wrap gap-2 mb-2">
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-900 text-[11px] text-slate-100 border border-slate-700">
                    גיל נהג: ${driverAge}
                </span>
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-900 text-[11px] text-slate-100 border border-slate-700">
                    ותק רישיון: ${licenseYears} שנים
                </span>
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-900 text-[11px] text-slate-100 border border-slate-700">
                    משפחה: ${familySize}, ${seats} מושבים
                </span>
            </div>

            <div class="flex flex-wrap gap-2 mb-2">
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-900 text-[11px] text-slate-100 border border-slate-700">
                    שימוש: ${mainUse}
                </span>
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-900 text-[11px] text-slate-100 border border-slate-700">
                    סגנון נהיגה: ${drivingStyle}
                </span>
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-900 text-[11px] text-slate-100 border border-slate-700">
                    מרכב מועדף: ${bodyStyle}
                </span>
            </div>

            <div class="flex flex-wrap gap-2 mt-1">
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-primary/10 text-[11px] text-primary border border-primary/40">
                    משקל אמינות: ${wReliability}/5
                </span>
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-primary/10 text-[11px] text-primary border border-primary/40">
                    חיסכון בדלק: ${wFuel}/5
                </span>
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-primary/10 text-[11px] text-primary border border-primary/40">
                    שמירת ערך: ${wResale}/5
                </span>
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-primary/10 text-[11px] text-primary border border-primary/40">
                    ביצועים: ${wPerf}/5
                </span>
                <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-primary/10 text-[11px] text-primary border border-primary/40">
                    נוחות: ${wComfort}/5
                </span>
            </div>

            <div class="mt-2 text-[11px] text-slate-400">
                העדפות דלק: ${fuels.length ? fuels.join(', ') : 'לא צוין'} · גיר: ${gears.length ? gears.join(', ') : 'לא צוין'}
            </div>
        `;
    }

    // --- כרטיסי Highlight (התאמה כללית, הכי זול, הכי אמין אם קיים) ---
    function getReliabilityScore(car) {
        const candidates = ['reliability_score', 'reliability_index', 'reliability'];
        for (const key of candidates) {
            if (car[key] != null) {
                const n = Number(car[key]);
                if (!Number.isNaN(n)) return n;
            }
        }
        return null;
    }

    function renderHighlightCards(cars) {
        if (!highlightCardsEl) return;

        if (!cars || !cars.length) {
            highlightCardsEl.innerHTML = '';
            return;
        }

        const byFit = [...cars].filter(c => c.fit_score != null).sort((a, b) => (b.fit_score || 0) - (a.fit_score || 0));
        const byAnnualCost = [...cars].filter(c => c.total_annual_cost != null).sort((a, b) => (a.total_annual_cost || Infinity) - (b.total_annual_cost || Infinity));
        const byReliability = [...cars].filter(c => getReliabilityScore(c) != null).sort((a, b) => (getReliabilityScore(b) || 0) - (getReliabilityScore(a) || 0));

        const bestFit = byFit[0] || null;
        const cheapest = byAnnualCost[0] || null;
        const mostReliable = byReliability[0] || null;

        const cards = [];

        if (bestFit) {
            cards.push({
                label: 'התאמה כללית הכי גבוהה',
                badge: 'המלצה ראשית',
                car: bestFit,
                chip: bestFit.fit_score != null ? `${Math.round(bestFit.fit_score)}% Fit` : '',
                text: 'מבוסס על כל הפרמטרים שהזנת: תקציב, שימוש, משפחה והעדפות. זה הדגם שהכי מתאים לפרופיל הכולל שלך.'
            });
        }

        if (cheapest) {
            cards.push({
                label: 'הכי זול להחזקה שנתי',
                badge: 'עלות שנתית',
                car: cheapest,
                chip: cheapest.total_annual_cost != null ? `${safeNum(cheapest.total_annual_cost)} ₪ בשנה` : '',
                text: 'מתוך כל הדגמים שהוצגו – זה הדגם עם העלות השנתית המוערכת הנמוכה ביותר (דלק/חשמל + תחזוקה בסיסית).'
            });
        }

        if (mostReliable && mostReliable !== bestFit) {
            const relScore = getReliabilityScore(mostReliable);
            cards.push({
                label: 'הכי חזק באמינות',
                badge: 'אמינות',
                car: mostReliable,
                chip: relScore != null ? `ציון אמינות ${safeNum(relScore, 1)}` : '',
                text: 'דגש על מינימום תקלות לאור נתוני אמינות והיסטוריית תקלות ביחס לשאר הדגמים שהוצגו.'
            });
        }

        if (!cards.length) {
            highlightCardsEl.innerHTML = '';
            return;
        }

        highlightCardsEl.innerHTML = cards.map((card) => {
            const title = `${card.car.brand || ''} ${card.car.model || ''}`.trim();
            const year = card.car.year || '';
            return `
                <article class="bg-slate-900/60 border border-slate-800 rounded-xl p-3 md:p-4 flex flex-col justify-between">
                    <div class="flex items-center justify-between mb-2">
                        <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-800 text-[10px] font-semibold text-slate-100 border border-slate-700">
                            ${card.badge}
                        </span>
                        <span class="text-[11px] text-slate-400">${card.label}</span>
                    </div>
                    <div class="mb-2">
                        <div class="text-sm md:text-base font-bold text-slate-100">
                            ${title} ${year ? '· ' + year : ''}
                        </div>
                        ${card.chip ? `
                            <div class="mt-1 inline-flex items-center px-2 py-0.5 rounded-full bg-primary/15 text-[11px] text-primary border border-primary/40">
                                ${card.chip}
                            </div>
                        ` : ''}
                    </div>
                    <p class="mt-1 text-[11px] md:text-xs text-slate-300 leading-relaxed">
                        ${card.text}
                    </p>
                </article>
            `;
        }).join('');
    }

    // --- תצוגת תוצאות מלאה ---
    function renderResults(data) {
        if (!resultsSection || !tableWrapper) return;

        const queries = Array.isArray(data.search_queries) ? data.search_queries : [];
        if (queriesEl) {
            if (queries.length) {
                queriesEl.innerHTML = `
                    <div class="text-[11px] text-slate-400">
                        <span class="font-semibold text-slate-300">שאילתות חיפוש שבוצעו:</span>
                        <ul class="mt-1 space-y-0.5">
                            ${queries.map(q => `<li>• ${q}</li>`).join('')}
                        </ul>
                    </div>
                `;
            } else {
                queriesEl.textContent = '';
            }
        }

        const cars = Array.isArray(data.recommended_cars) ? data.recommended_cars : [];
        if (!cars.length) {
            if (profileSummaryEl) profileSummaryEl.innerHTML = '';
            if (highlightCardsEl) highlightCardsEl.innerHTML = '';
            tableWrapper.innerHTML =
                '<p class="text-sm text-slate-400">לא התקבלו המלצות. ייתכן שהגבלות התקציב/שנים קשיחות מדי.</p>';
            resultsSection.classList.remove('hidden');
            resultsSection.scrollIntoView({behavior: 'smooth', block: 'start'});
            return;
        }

        // סיכום פרופיל לפי מה שהוזן בטופס
        renderProfileSummary();

        // כרטיסי Highlight לפי התוצאות
        renderHighlightCards(cars);

        // מיון לפי Fit Score, גדול לקטן
        cars.sort((a, b) => (b.fit_score || 0) - (a.fit_score || 0));

        const rows = cars.map((car) => {
            const fit = car.fit_score != null ? Math.round(car.fit_score) : null;
            let fitClass = 'bg-slate-800 text-slate-100';
            if (fit !== null) {
                if (fit >= 85) fitClass = 'bg-emerald-500/90 text-white';
                else if (fit >= 70) fitClass = 'bg-amber-500/90 text-slate-900';
                else fitClass = 'bg-slate-700 text-slate-100';
            }

            const comparison = car.comparison_comment || '';
            const annualCost = car.total_annual_cost != null ? `${safeNum(car.total_annual_cost)} ₪` : '';

            return `
                <tr class="border-b border-slate-800/80 hover:bg-slate-900/60 text-xs md:text-sm">
                    <td class="px-2 py-2 md:px-3 md:py-2.5 whitespace-nowrap">
                        <div class="flex flex-col">
                            <span class="font-semibold text-slate-100">${car.brand || ''} ${car.model || ''}</span>
                            <span class="text-[11px] text-slate-400">שנה: ${car.year || ''}</span>
                        </div>
                    </td>
                    <td class="px-2 py-2 md:px-3 md:py-2.5 whitespace-nowrap text-[11px] md:text-xs text-slate-200">
                        <div>${car.fuel || ''}</div>
                        <div>${car.gear || ''}${car.turbo ? ` • טורבו: ${car.turbo}` : ''}</div>
                    </td>
                    <td class="px-2 py-2 md:px-3 md:py-2.5 whitespace-nowrap text-[11px] md:text-xs text-slate-200">
                        ${formatPriceRange(car.price_range_nis)}
                    </td>
                    <td class="px-2 py-2 md:px-3 md:py-2.5 whitespace-nowrap text-[11px] md:text-xs text-slate-200">
                        ${annualCost}
                    </td>
                    <td class="px-2 py-2 md:px-3 md:py-2.5 whitespace-nowrap">
                        <span class="inline-flex items-center justify-center min-w-[44px] px-2 py-1 rounded-full text-[11px] font-bold ${fitClass}">
                            ${fit !== null ? fit + '%' : '?'}
                        </span>
                    </td>
                    <td class="hidden md:table-cell px-2 py-2 md:px-3 md:py-2.5 text-[11px] text-slate-300 max-w-xs">
                        ${comparison}
                    </td>
                </tr>
            `;
        }).join('');

        tableWrapper.innerHTML = `
            <div class="mb-2 text-[11px] text-slate-400">
                הטבלה מדורגת מההתאמה הגבוהה לנמוכה על סמך הפרופיל שהזנת.
            </div>
            <div class="overflow-x-auto">
                <table class="min-w-full text-right border-separate border-spacing-y-1">
                    <thead class="text-[11px] md:text-xs text-slate-400">
                        <tr>
                            <th class="px-2 md:px-3 py-1 font-semibold">דגם</th>
                            <th class="px-2 md:px-3 py-1 font-semibold">דלק / גיר</th>
                            <th class="px-2 md:px-3 py-1 font-semibold">טווח מחיר (₪)</th>
                            <th class="px-2 md:px-3 py-1 font-semibold">עלות שנתית משוערת</th>
                            <th class="px-2 md:px-3 py-1 font-semibold">Fit Score</th>
                            <th class="hidden md:table-cell px-2 md:px-3 py-1 font-semibold">הערת השוואה</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
            </div>
        `;

        resultsSection.classList.remove('hidden');
        resultsSection.scrollIntoView({behavior: 'smooth', block: 'start'});
    }

    // --- Submit ---
    async function handleSubmit(e) {
        e.preventDefault();

        if (errorEl) {
            errorEl.textContent = '';
            errorEl.classList.add('hidden');
        }

        // בדיקת הסכמה מעל גיל 18 + תנאים
        if (consentCheckbox && !consentCheckbox.checked) {
            if (errorEl) {
                errorEl.textContent =
                    'יש לאשר שאתה מעל גיל 18 ומסכים לתקנון ולמדיניות הפרטיות לפני הפעלת מנוע ההמלצות.';
                errorEl.classList.remove('hidden');
            }
            return;
        }

        const payload = buildPayload();

        if (!payload.budget_max || payload.budget_max <= 0 || payload.budget_min > payload.budget_max) {
            if (errorEl) {
                errorEl.textContent =
                    'בדוק שהתקציב המינימלי קטן מהתקציב המקסימלי ושערכי התקציב תקינים.';
                errorEl.classList.remove('hidden');
            }
            return;
        }

        setSubmitting(true);
        try {
            const res = await fetch('/advisor_api', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (!res.ok || data.error) {
                if (errorEl) {
                    errorEl.textContent =
                        data.error || 'שגיאת שרת בעת הפעלת מנוע ההמלצות.';
                    errorEl.classList.remove('hidden');
                } else {
                    alert(data.error || 'שגיאת שרת');
                }
                return;
            }
            renderResults(data);
        } catch (err) {
            console.error(err);
            if (errorEl) {
                errorEl.textContent =
                    'שגיאה כללית בחיבור לשרת. נסה שוב מאוחר יותר.';
                errorEl.classList.remove('hidden');
            } else {
                alert('שגיאה כללית בחיבור לשרת');
            }
        } finally {
            setSubmitting(false);
        }
    }

    form.addEventListener('submit', handleSubmit);
})();
