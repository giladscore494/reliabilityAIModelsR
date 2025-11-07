document.addEventListener("DOMContentLoaded", () => {
    // איתור כל האלמנטים הרלוונטיים בדף
    const makeSelect = document.getElementById("make");
    const modelSelect = document.getElementById("model");
    const yearSelect = document.getElementById("year");
    const carForm = document.getElementById("car-form");
    const resultsContainer = document.getElementById("results-container");
    const resultsContent = document.getElementById("results-content");
    const submitButton = document.getElementById("submit-button");

    // פונקציה לעדכון רשימת הדגמים כשבוחרים יצרן
    makeSelect.addEventListener("change", () => {
        const selectedMake = makeSelect.value;
        modelSelect.innerHTML = '<option value="">בחר דגם...</option>'; // איפוס
        yearSelect.innerHTML = '<option value="">בחר דגם תחילה...</option>'; // איפוס
        modelSelect.disabled = true;
        yearSelect.disabled = true;

        if (selectedMake && carModelsData[selectedMake]) {
            modelSelect.disabled = false;
            // לולאה על כל הדגמים של היצרן הנבחר
            carModelsData[selectedMake].forEach(modelLabel => {
                const option = document.createElement("option");
                option.value = modelLabel;
                option.textContent = modelLabel;
                modelSelect.appendChild(option);
            });
        }
    });

    // פונקציה לעדכון טווח השנים כשבוחרים דגם
    modelSelect.addEventListener("change", () => {
        const selectedModelLabel = modelSelect.value;
        yearSelect.innerHTML = '<option value="">בחר שנה...</option>'; // איפוס
        yearSelect.disabled = true;

        if (selectedModelLabel) {
            // חילוץ השנים מתוך הטקסט (למשל "Golf (2004-2025)")
            const match = selectedModelLabel.match(/\((\d{4})\s*-\s*(\d{4})\)/);
            if (match) {
                yearSelect.disabled = false;
                const startYear = parseInt(match[1]);
                const endYear = parseInt(match[2]);
                const currentYear = new Date().getFullYear();
                
                // יצירת רשימת שנים (מהחדש לישן)
                for (let year = endYear; year >= startYear; year--) {
                    const option = document.createElement("option");
                    option.value = year;
                    option.textContent = year;
                    // בחירת ברירת מחדל (למשל, 5 שנים אחורה)
                    if (year === Math.min(endYear, Math.max(startYear, currentYear - 5))) {
                        option.selected = true;
                    }
                    yearSelect.appendChild(option);
                }
            }
        }
    });

    // --- הטיפול המרכזי: שליחת הטופס ---
    carForm.addEventListener("submit", async (e) => {
        e.preventDefault(); // מניעת רענון הדף
        
        // --- ★ שינוי כאן: הפעלת הספינר ---
        submitButton.disabled = true;
        submitButton.querySelector('.button-text').classList.add('hidden');
        submitButton.querySelector('.spinner').classList.remove('hidden');
        resultsContainer.classList.add("hidden");
        resultsContent.innerHTML = '<progress style="width: 100%"></progress>'; // אנימציית טעינה ראשונית

        // איסוף כל הנתונים מהטופס
        const formData = new FormData(carForm);
        const data = {};
        formData.forEach((value, key) => {
            if (key === 'model') {
                // ניקוי הדגם מהשנים (מ-"Golf (2004-2025)" ל-"Golf")
                data[key] = value.split(' (')[0].trim();
            } else {
                data[key] = value;
            }
        });

        try {
            // --- שליחת הבקשה לשרת (ל-API ב-app.py) ---
            const response = await fetch("/analyze", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(data), // המרת האובייקט ל-JSON
            });

            // קבלת התשובה מהשרת
            const resultData = await response.json();

            // טיפול בשגיאות שחזרו מהשרת
            if (!response.ok) {
                throw new Error(resultData.error || `HTTP error! status: ${response.status}`);
            }

            // הצלחה! הצגת התוצאות
            renderResults(resultData);
            resultsContainer.classList.remove("hidden"); // הצגת התוצאות

        } catch (error) {
            // טיפול בשגיאות תקשורת או שגיאות קריטיות
            console.error("Error during analysis:", error);
            resultsContent.innerHTML = `<mark class="error">❌ נכשלתי ביצירת הניתוח: ${error.message}</mark>`;
            resultsContainer.classList.remove("hidden"); // הצגת השגיאה
        } finally {
            // --- ★ שינוי כאן: החזרת הכפתור למצב רגיל ---
            submitButton.disabled = false;
            submitButton.querySelector('.button-text').classList.remove('hidden');
            submitButton.querySelector('.spinner').classList.add('hidden');
        }
    });

    // פונקציה להצגת התוצאות ב-HTML
    function renderResults(data) {
        let html = '';

        // ציון
        html += `<h3>ציון אמינות משוקלל: ${data.base_score_calculated || 0} / 100</h3>`;

        // אזהרות
        if (data.km_warn) {
            html += `<mark>⚠️ טווח הק״מ השמור שונה מהקלט. ייתכן שהציון היה משתנה לפי ק״מ.</mark>`;
        }
        if (data.mileage_note) {
            html += `<p><strong>הערת קילומטראז':</strong> ${data.mileage_note}</p>`;
        }

        // סיכום
        if (data.reliability_summary) {
            html += `<p>${data.reliability_summary}</p>`;
        }

        // טאבים (נבנה בצורה פשוטה)
        html += `<hr style="border-color: var(--border-color); margin-top: 1.5rem; margin-bottom: 1.5rem;">`;
        
        // פירוט ציון
        html += `<h4>📊 פירוט (1–10)</h4><ul>`;
        const breakdown = data.score_breakdown || {};
        html += `<li>מנוע וגיר: <strong>${breakdown.engine_transmission_score || 'N/A'}</strong>/10</li>`;
        html += `<li>חשמל/אלקטרוניקה: <strong>${breakdown.electrical_score || 'N/A'}</strong>/10</li>`;
        html += `<li>מתלים/בלמים: <strong>${breakdown.suspension_brakes_score || 'N/A'}</strong>/10</li>`;
        html += `<li>עלות אחזקה: <strong>${breakdown.maintenance_cost_score || 'N/A'}</strong>/10</li>`;
        html += `<li>שביעות רצון: <strong>${breakdown.satisfaction_score || 'N/A'}</strong>/10</li>`;
        html += `<li>ריקולים: <strong>${breakdown.recalls_score || 'N/A'}</strong>/10</li>`;
        html += `</ul>`;

        // תקלות ועלויות
        html += `<h4>🔧 תקלות ועלויות</h4>`;
        if (data.common_issues && data.common_issues.length > 0) {
            html += `<strong>תקלות נפוצות:</strong><ul>`;
            data.common_issues.forEach(issue => html += `<li>${issue}</li>`);
            html += `</ul>`;
        }
        if (data.issues_with_costs && data.issues_with_costs.length > 0) {
            html += `<strong>עלויות תיקון (אינדיקטיבי):</strong><ul>`;
            data.issues_with_costs.forEach(item => {
                html += `<li>${item.issue || ''}: כ-${item.avg_cost_ILS || 'N/A'} ₪ (חומרה: ${item.severity || 'N/A'})</li>`;
            });
            html += `</ul>`;
        }
        
        // בדיקות
        html += `<h4>🔬 בדיקות מומלצות</h4>`;
        if (data.recommended_checks && data.recommended_checks.length > 0) {
            html += `<ul>`;
            data.recommended_checks.forEach(check => html += `<li>${check}</li>`);
            html += `</ul>`;
        } else {
            html += `<p>אין המלצות בדיקה ספציפיות.</p>`;
        }

        // מתחרים
        html += `<h4>🚗 מתחרים נפוצים</h4>`;
        if (data.common_competitors_brief && data.common_competitors_brief.length > 0) {
            data.common_competitors_brief.forEach(comp => {
                html += `<p><strong>${comp.model || ''}:</strong> ${comp.brief_summary || ''}</p>`;
            });
        } else {
            html += `<p>אין נתוני מתחרים.</p>`;
        }

        // מקור
        html += `<small>${data.source_tag || ''}</small>`;

        // הזרקת כל ה-HTML שנוצר לתוך הדף
        resultsContent.innerHTML = html;
    }
});
