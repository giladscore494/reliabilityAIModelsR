document.addEventListener("DOMContentLoaded", () => {
    if (typeof userIsAuthenticated === 'undefined' || !userIsAuthenticated) {
        console.log("משתמש לא מחובר, הטופס מושבת.");
        return;
    }

    const makeSelect = document.getElementById("make");
    const modelSelect = document.getElementById("model");
    const yearSelect = document.getElementById("year");
    const carForm = document.getElementById("car-form");
    const resultsContainer = document.getElementById("results-container");
    const resultsContent = document.getElementById("results-content");
    const submitButton = document.getElementById("submit-button");

    makeSelect.addEventListener("change", () => {
        const selectedMake = makeSelect.value;
        modelSelect.innerHTML = '<option value="">בחר דגם...</option>';
        yearSelect.innerHTML = '<option value="">בחר דגם תחילה...</option>';
        modelSelect.disabled = true;
        yearSelect.disabled = true;

        if (selectedMake && carModelsData[selectedMake]) {
            modelSelect.disabled = false;
            carModelsData[selectedMake].forEach(modelLabel => {
                const option = document.createElement("option");
                option.value = modelLabel;
                option.textContent = modelLabel;
                modelSelect.appendChild(option);
            });
        }
    });

    modelSelect.addEventListener("change", () => {
        const selectedModelLabel = modelSelect.value;
        yearSelect.innerHTML = '<option value="">בחר שנה...</option>';
        yearSelect.disabled = true;

        if (selectedModelLabel) {
            const match = selectedModelLabel.match(/\((\d{4})\s*-\s*(\d{4})\)/);
            if (match) {
                yearSelect.disabled = false;
                const startYear = parseInt(match[1]);
                const endYear = parseInt(match[2]);
                const currentYear = new Date().getFullYear();
                
                for (let year = endYear; year >= startYear; year--) {
                    const option = document.createElement("option");
                    option.value = year;
                    option.textContent = year;
                    if (year === Math.min(endYear, Math.max(startYear, currentYear - 5))) {
                        option.selected = true;
                    }
                    yearSelect.appendChild(option);
                }
            }
        }
    });

    carForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        // ✅ בדיקת אישור חוקי
        const legalConfirm = document.getElementById('legal-confirm');
        const legalError = document.getElementById('legal-error');

        if (legalConfirm && !legalConfirm.checked) {
            legalError.style.display = 'block';
            return;
        } else {
            legalError.style.display = 'none';
        }

        submitButton.disabled = true;
        submitButton.querySelector('.button-text').classList.add('hidden');
        submitButton.querySelector('.spinner').classList.remove('hidden');
        resultsContainer.classList.add("hidden");
        resultsContent.innerHTML = '<progress style="width: 100%"></progress>';

        const formData = new FormData(carForm);
        const data = {};
        formData.forEach((value, key) => {
            if (key === 'model') {
                data[key] = value.split(' (')[0].trim();
            } else {
                data[key] = value;
            }
        });

        try {
            const response = await fetch("/analyze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data),
            });

            const resultData = await response.json();

            if (!response.ok) {
                throw new Error(resultData.error || `HTTP error! status: ${response.status}`);
            }
            
            renderResults(resultData);
            resultsContainer.classList.remove("hidden");

        } catch (error) {
            console.error("Error during analysis:", error);
            resultsContent.innerHTML = `<mark class="error">❌ נכשלתי ביצירת הניתוח: ${error.message}</mark>`;
            resultsContainer.classList.remove("hidden");
        } finally {
            submitButton.disabled = false;
            submitButton.querySelector('.button-text').classList.remove('hidden');
            submitButton.querySelector('.spinner').classList.add('hidden');
        }
    });

    function renderResults(data) {
        let html = '';

        html += `<h3>ציון אמינות משוקלל</h3>`;
        html += `<div class="score-value">${data.base_score_calculated || 0} / 100</div>`;

        if (data.km_warn) {
            html += `<mark>⚠️ טווח הק״מ השמור שונה מהקלט. ייתכן שהציון היה משתנה לפי ק״מ.</mark>`;
        }
        if (data.mileage_note) {
            html += `<p style="text-align:center;"><strong>הערת קילומטראז':</strong> ${data.mileage_note}</p>`;
        }
        if (data.reliability_summary) {
            html += `<p class="summary-text">${data.reliability_summary}</p>`;
        }

        html += `
            <div class="result-tabs">
                <div class="tab active" data-tab="tab-details">📊 פירוט הציון</div>
                <div class="tab" data-tab="tab-issues">🔧 תקלות ועלויות</div>
                <div class="tab" data-tab="tab-checks">🔬 בדיקות מומלצות</div>
                <div class="tab" data-tab="tab-competitors">🚗 מתחרים</div>
            </div>
        `;

        const breakdown = data.score_breakdown || {};
        html += `<div id="tab-details" class="tab-content active"><ul class="score-breakdown-list">`;
        html += `<li><span>מנוע וגיר</span> <span>${breakdown.engine_transmission_score || 'N/A'}/10</span></li>`;
        html += `<li><span>חשמל/אלקטרוניקה</span> <span>${breakdown.electrical_score || 'N/A'}/10</span></li>`;
        html += `<li><span>מתלים/בלמים</span> <span>${breakdown.suspension_brakes_score || 'N/A'}/10</span></li>`;
        html += `<li><span>עלות אחזקה</span> <span>${breakdown.maintenance_cost_score || 'N/A'}/10</span></li>`;
        html += `<li><span>שביעות רצון</span> <span>${breakdown.satisfaction_score || 'N/A'}/10</span></li>`;
        html += `<li><span>ריקולים</span> <span>${breakdown.recalls_score || 'N/A'}/10</span></li>`;
        html += `</ul></div>`;

        html += `<div id="tab-issues" class="tab-content">`;
        if (data.common_issues && data.common_issues.length > 0) {
            html += `<strong>תקלות נפוצות:</strong><ul>`;
            data.common_issues.forEach(issue => html += `<li>${issue}</li>`);
            html += `</ul><br>`;
        }
        if (data.issues_with_costs && data.issues_with_costs.length > 0) {
            html += `<strong>עלויות תיקון (אינדיקטיבי):</strong><ul>`;
            data.issues_with_costs.forEach(item => {
                html += `<li>${item.issue || ''}: כ-${item.avg_cost_ILS || 'N/A'} ₪ (חומרה: ${item.severity || 'N/A'})</li>`;
            });
            html += `</ul>`;
        }
        html += `</div>`;

        html += `<div id="tab-checks" class="tab-content">`;
        if (data.recommended_checks && data.recommended_checks.length > 0) {
            html += `<ul>`;
            data.recommended_checks.forEach(check => html += `<li>${check}</li>`);
            html += `</ul>`;
        } else {
            html += `<p>אין המלצות בדיקה ספציפיות.</p>`;
        }
        html += `</div>`;

        html += `<div id="tab-competitors" class="tab-content">`;
        if (data.common_competitors_brief && data.common_competitors_brief.length > 0) {
            data.common_competitors_brief.forEach(comp => {
                html += `<div class="competitor-item"><strong>${comp.model || ''}:</strong> ${comp.brief_summary || ''}</div>`;
            });
        } else {
            html += `<p>אין נתוני מתחרים.</p>`;
        }
        html += `</div>`;

        html += `<small>${data.source_tag || ''}</small>`;

        resultsContent.innerHTML = html;
        activateTabs();
    }

    function activateTabs() {
        const tabs = resultsContent.querySelectorAll('.tab');
        const tabContents = resultsContent.querySelectorAll('.tab-content');

        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                tabs.forEach(t => t.classList.remove('active'));
                tabContents.forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                resultsContent.querySelector(`#${tab.dataset.tab}`).classList.add('active');
            });
        });
    }
});
