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
            tableWrapper.innerHTML =
                '<p class="text-sm text-slate-400">לא התקבלו המלצות. ייתכן שהגבלות התקציב/שנים קשיחות מדי.</p>';
            resultsSection.classList.remove('hidden');
            resultsSection.scrollIntoView({behavior: 'smooth', block: 'start'});
            return;
        }

        cars.sort((a, b) => (b.fit_score || 0) - (a.fit_score || 0));

        const rows = cars.map((car) => {
            const fit = car.fit_score != null ? Math.round(car.fit_score) : null;
            let fitClass = 'bg-slate-800 text-slate-100';
            if (fit !== null) {
                if (fit >= 85) fitClass = 'bg-emerald-500/90 text-white';
                else if (fit >= 70) fitClass = 'bg-amber-500/90 text-slate-900';
                else fitClass = 'bg-slate-700 text-slate-100';
            }

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
                        ${car.total_annual_cost != null ? `${safeNum(car.total_annual_cost)} ₪` : ''}
                    </td>
                    <td class="px-2 py-2 md:px-3 md:py-2.5 whitespace-nowrap">
                        <span class="inline-flex items-center justify-center min-w-[44px] px-2 py-1 rounded-full text-[11px] font-bold ${fitClass}">
                            ${fit !== null ? fit + '%' : '?'}
                        </span>
                    </td>
                    <td class="hidden md:table-cell px-2 py-2 md:px-3 md:py-2.5 text-[11px] text-slate-300 max-w-xs">
                        ${car.comparison_comment || ''}
                    </td>
                </tr>
            `;
        }).join('');

        tableWrapper.innerHTML = `
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
