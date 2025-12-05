// קובץ JS חיצוני — אין כאן תבניות Jinja, לכן אין סכנת {{ }}
(function () {
    // עזר: קריאת JSON מתוך תגית <script type="application/json">
    function getSafeData(elementId, defaultValue) {
        try {
            const el = document.getElementById(elementId);
            if (!el) return defaultValue;
            const text = (el.textContent || "").trim();
            // אם השרת לא רינדר (למקרה של שגיאה), נחזיר ברירת מחדל
            if (text.startsWith("{{")) return defaultValue;
            return JSON.parse(text);
        } catch (e) {
            console.error("Error parsing data from #" + elementId, e);
            return defaultValue;
        }
    }

    // נתונים גלובליים שנקראים מה-HTML
    const userIsAuthenticated = getSafeData("auth-data", false);
    const carModelsData = getSafeData("car-data", {});

    // מצב גלובלי לטוגל של הסיכום המעמיק
    let summaryDetailedOpen = false;

    // חשיפה לגלובלי כי כפתורי הטאבים קוראים מה-HTML
    window.openTab = function (evt, tabName) {
        document.querySelectorAll(".tab-content").forEach(tc => tc.classList.remove("active"));
        document.querySelectorAll(".tab-btn").forEach(tb => tb.classList.remove("active"));
        const target = document.getElementById(tabName);
        if (target) target.classList.add("active");
        if (evt && evt.currentTarget) evt.currentTarget.classList.add("active");
    };

    // פונקציית הצגה לתוצאות (חשופה כדי שנוכל להחליף בעתיד)
    window.displayResultsOverride = function (data) {
        const container = document.getElementById('results-container');
        const scoreContainer = document.getElementById('reliability-score-container');

        let score = 0;
        if (data && data.base_score_calculated != null) {
            const asNum = parseFloat(data.base_score_calculated);
            if (!Number.isNaN(asNum)) score = asNum;
        } else {
            const m = JSON.stringify(data || {}).match(/ציון.*?(\d{1,3})/);
            if (m && m[1]) score = parseInt(m[1], 10);
        }
        score = Math.round(score);

        let scoreColor = 'bg-warning', scoreText = 'אמינות בינונית';
        if (score >= 80) { scoreColor = 'bg-success'; scoreText = 'רכב אמין מאוד 🏆'; }
        else if (score >= 70) { scoreColor = 'bg-primary'; scoreText = 'רכב אמין ✅'; }
        else if (score > 0 && score <= 50) { scoreColor = 'bg-danger'; scoreText = 'פוטנציאל לאמינות נמוכה ⚠️'; }
        else if (score === 0) { scoreColor = 'bg-slate-500'; scoreText = 'ציון לא זמין'; }

        scoreContainer.innerHTML = `
            <div class="score-circle ${scoreColor} mb-4">
                <span class="text-5xl">${score > 0 ? score : '?'}</span>
                <span class="text-sm opacity-80">מתוך 100</span>
            </div>
            <h3 class="text-2xl font-bold ${scoreColor.replace('bg-', 'text-')}">${scoreText}</h3>
        `;

        // --- סיכום פשוט כברירת מחדל + אפשרות להרחבה מקצועית ---
        const simpleEl = document.getElementById('summary-simple-text');
        const detailedEl = document.getElementById('summary-detailed-text');
        const toggleBtn = document.getElementById('summary-toggle-btn');
        const detailedBlock = document.getElementById('summary-detailed-block');

        let simpleText = "";
        let detailedText = "";

        if (data) {
            if (data.reliability_summary_simple) {
                simpleText = data.reliability_summary_simple;
            }
            if (data.reliability_summary) {
                detailedText = data.reliability_summary;
            } else if (data.response) {
                // fallback: אם המודל החזיר רק response
                detailedText = data.response;
            }
            // אם אין טקסט פשוט אבל יש הסבר מקצועי – נשתמש בו כפשוט
            if (!simpleText && detailedText) {
                simpleText = detailedText;
            }
        }

        if (simpleEl) {
            simpleEl.innerHTML = simpleText ? marked.parse(simpleText) : "";
        }
        if (detailedEl) {
            detailedEl.innerHTML = detailedText ? marked.parse(detailedText) : "";
        }

        // ניהול מצב כפתור ההרחבה
        summaryDetailedOpen = false;
        if (toggleBtn && detailedBlock) {
            if (detailedText) {
                toggleBtn.classList.remove('hidden');
                detailedBlock.classList.add('hidden');
                toggleBtn.textContent = 'להרחבה מקצועית';
            } else {
                // אין הסבר מקצועי – לא מציגים את הכפתור ולא את הבלוק
                toggleBtn.classList.add('hidden');
                detailedBlock.classList.add('hidden');
            }
        }

        // --- תקלות נפוצות ---
        if (data && Array.isArray(data.common_issues)) {
            let faultsHtml = '<ul class="list-disc pr-5 space-y-2">';
            data.common_issues.forEach(issue => { faultsHtml += `<li>${issue}</li>`; });
            faultsHtml += '</ul>';

            if (Array.isArray(data.issues_with_costs)) {
                faultsHtml += '<h4 class="text-xl font-bold mt-6 mb-3">עלויות תיקון משוערות:</h4><ul class="space-y-3">';
                data.issues_with_costs.forEach(item => {
                    const price = (item && item.avg_cost_ILS != null) ? item.avg_cost_ILS : '';
                    const issue = (item && item.issue) ? item.issue : '';
                    faultsHtml += `<li class="bg-slate-800/50 p-3 rounded-lg flex justify-between items-center"><span>${issue}</span><span class="font-bold text-primary">${price} ₪</span></li>`;
                });
                faultsHtml += '</ul>';
            }
            document.getElementById('faults').innerHTML = faultsHtml;
        }

        // --- עלויות אחזקה ---
        if (data && data.avg_repair_cost_ILS != null) {
            const maintenanceScore = (data.maintenance_cost_score != null) ? `<p>ציון עלויות אחזקה: <strong>${data.maintenance_cost_score}/10</strong></p>` : '';
            document.getElementById('costs').innerHTML = `
                <h4 class="text-xl font-bold mb-3">עלות תחזוקה שנתית ממוצעת:</h4>
                <p class="text-3xl font-black text-primary mb-6">${data.avg_repair_cost_ILS} ₪</p>
                ${maintenanceScore}
            `;
        }

        // --- מתחרים ---
        if (data && Array.isArray(data.common_competitors_brief)) {
            let compHtml = '<div class="grid grid-cols-1 md:grid-cols-2 gap-4">';
            data.common_competitors_brief.forEach(comp => {
                const model = comp && comp.model ? comp.model : '';
                const brief = comp && comp.brief_summary ? comp.brief_summary : '';
                compHtml += `<div class="bg-slate-800/50 p-4 rounded-xl border border-slate-700/50"><h5 class="font-bold text-lg mb-2 text-indigo-300">${model}</h5><p class="text-sm opacity-80">${brief}</p></div>`;
            });
            compHtml += '</div>';
            document.getElementById('competitors').innerHTML = compHtml;
        }

        container.classList.remove('hidden');
        container.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    // לוגיקת טפסים ותלויות
    document.addEventListener('DOMContentLoaded', () => {
        const form = document.getElementById('car-form');
        const makeSelect = document.getElementById('make');
        const modelSelect = document.getElementById('model');
        const yearSelect = document.getElementById('year');
        const submitButton = document.getElementById('submit-button');
        const spinner = submitButton ? submitButton.querySelector('.spinner') : null;
        const resultsContainer = document.getElementById('results-container');
        const legalConfirm = document.getElementById('legal-confirm');
        const legalError = document.getElementById('legal-error');

        const toggleBtn = document.getElementById('summary-toggle-btn');
        const detailedBlock = document.getElementById('summary-detailed-block');

        // טוגל בין סיכום פשוט לסיכום מקצועי
        if (toggleBtn && detailedBlock) {
            toggleBtn.addEventListener('click', () => {
                summaryDetailedOpen = !summaryDetailedOpen;
                if (summaryDetailedOpen) {
                    detailedBlock.classList.remove('hidden');
                    toggleBtn.textContent = 'להסבר קצר';
                } else {
                    detailedBlock.classList.add('hidden');
                    toggleBtn.textContent = 'להרחבה מקצועית';
                }
            });
        }

        // 1) תלות יצרן → דגם
        if (makeSelect && modelSelect && yearSelect) {
            makeSelect.addEventListener('change', () => {
                const selectedMake = makeSelect.value;
                modelSelect.innerHTML = '<option value="">Select Model...</option>';
                yearSelect.innerHTML = '<option value="">Select Make First...</option>';
                modelSelect.disabled = true;
                yearSelect.disabled = true;

                if (selectedMake && carModelsData && carModelsData[selectedMake]) {
                    const modelsData = carModelsData[selectedMake];
                    let models = [];

                    if (Array.isArray(modelsData)) {
                        models = [...modelsData].sort();
                    } else if (typeof modelsData === 'object' && modelsData !== null) {
                        models = Object.keys(modelsData).sort();
                    }

                    if (models.length) {
                        models.forEach(m => {
                            const opt = document.createElement('option');
                            opt.value = m;
                            opt.textContent = m;
                            modelSelect.appendChild(opt);
                        });
                        modelSelect.disabled = false;
                    }
                }
            });

            // 2) תלות דגם → שנתון
            modelSelect.addEventListener('change', () => {
                const selectedMake = makeSelect.value;
                const selectedModel = modelSelect.value;

                yearSelect.innerHTML = '<option value="">Select Year...</option>';
                yearSelect.disabled = true;

                if (selectedMake && selectedModel && carModelsData[selectedMake]) {
                    let years = [];
                    const modelsData = carModelsData[selectedMake];

                    if (Array.isArray(modelsData)) {
                        // אין מפה לשנים – טווח כללי
                        for (let y = 2025; y >= 2000; y--) years.push(y);
                    } else if (typeof modelsData === 'object' && modelsData !== null && modelsData[selectedModel]) {
                        years = Array.isArray(modelsData[selectedModel]) ? [...modelsData[selectedModel]] : [];
                    }

                    if (!years.length) {
                        for (let y = 2025; y >= 2000; y--) years.push(y);
                    }

                    years.sort((a, b) => b - a).forEach(y => {
                        const opt = document.createElement('option');
                        opt.value = y;
                        opt.textContent = y;
                        yearSelect.appendChild(opt);
                    });
                    yearSelect.disabled = false;
                }
            });
        }

        // 3) שליחת טופס
        if (form) {
            form.addEventListener('submit', async (e) => {
                e.preventDefault();

                if (!userIsAuthenticated) {
                    alert("אנא התחבר כדי לבצע חיפוש.");
                    window.location.href = '/login';
                    return;
                }

                if (legalConfirm && !legalConfirm.checked) {
                    if (legalError) {
                        legalError.classList.remove('hidden');
                        legalError.classList.add('flex');
                    }
                    return;
                } else if (legalError) {
                    legalError.classList.add('hidden');
                    legalError.classList.remove('flex');
                }

                if (submitButton) {
                    submitButton.disabled = true;
                    submitButton.classList.add('opacity-75', 'cursor-not-allowed');
                }
                if (spinner) spinner.classList.remove('hidden');
                if (resultsContainer) resultsContainer.classList.add('hidden');

                const formData = new FormData(form);
                const payload = Object.fromEntries(formData.entries());

                try {
                    const resp = await fetch('/analyze', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });

                    const contentType = resp.headers.get('content-type') || '';
                    if (!contentType.includes('application/json')) {
                        const txt = await resp.text();
                        console.error('Non-JSON response:', txt.slice(0, 300));
                        throw new Error(`שגיאת שרת (Status ${resp.status}).`);
                    }
                    const data = await resp.json();
                    if (!resp.ok) {
                        const msg = data && data.error ? data.error : 'שגיאה בביצוע החיפוש';
                        throw new Error(msg);
                    }

                    if (typeof window.displayResultsOverride === 'function') {
                        window.displayResultsOverride(data);
                    } else {
                        console.log('Results:', data);
                        alert('התקבלו תוצאות, אך רכיב התצוגה חסר.');
                    }
                } catch (err) {
                    console.error('Search error:', err);
                    alert('אירעה שגיאה: ' + (err && err.message ? err.message : err));
                } finally {
                    if (submitButton) {
                        submitButton.disabled = false;
                        submitButton.classList.remove('opacity-75', 'cursor-not-allowed');
                    }
                    if (spinner) spinner.classList.add('hidden');
                }
            });
        }
    });
})();
