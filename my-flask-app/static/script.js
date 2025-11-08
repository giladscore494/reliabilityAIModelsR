document.addEventListener('DOMContentLoaded', () => {
    // אלמנטים מה-DOM
    const form = document.getElementById('car-form');
    const makeSelect = document.getElementById('make');
    const modelSelect = document.getElementById('model');
    const yearSelect = document.getElementById('year');
    const submitButton = document.getElementById('submit-button');
    const spinner = submitButton ? submitButton.querySelector('.spinner') : null;
    const buttonText = submitButton ? submitButton.querySelector('.button-text') : null;
    const resultsContainer = document.getElementById('results-container');
    const legalConfirm = document.getElementById('legal-confirm');
    const legalError = document.getElementById('legal-error');

    // משתני עזר גלובליים (מוגדרים ב-HTML)
    // userIsAuthenticated, carModelsData

    // === 1. לוגיקת בחירת רכב (Dropdowns תלויים) ===
    if (makeSelect && modelSelect && yearSelect) {
        // בעת בחירת יצרן
        makeSelect.addEventListener('change', () => {
            const selectedMake = makeSelect.value;
            modelSelect.innerHTML = '<option value="">בחר דגם...</option>';
            yearSelect.innerHTML = '<option value="">בחר יצרן תחילה...</option>';
            yearSelect.disabled = true;

            if (selectedMake && carModelsData[selectedMake]) {
                const models = Object.keys(carModelsData[selectedMake]).sort();
                models.forEach(model => {
                    const option = document.createElement('option');
                    option.value = model;
                    option.textContent = model;
                    modelSelect.appendChild(option);
                });
                modelSelect.disabled = false;
            } else {
                modelSelect.disabled = true;
            }
        });

        // בעת בחירת דגם
        modelSelect.addEventListener('change', () => {
            const selectedMake = makeSelect.value;
            const selectedModel = modelSelect.value;
            yearSelect.innerHTML = '<option value="">בחר שנה...</option>';

            if (selectedMake && selectedModel && carModelsData[selectedMake][selectedModel]) {
                const years = carModelsData[selectedMake][selectedModel].sort((a, b) => b - a); // מיון יורד
                years.forEach(year => {
                    const option = document.createElement('option');
                    option.value = year;
                    option.textContent = year;
                    yearSelect.appendChild(option);
                });
                yearSelect.disabled = false;
            } else {
                yearSelect.disabled = true;
            }
        });
    }

    // === 2. שליחת הטופס וטיפול בתוצאות ===
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            // ולידציה: האם המשתמש מחובר?
            if (!userIsAuthenticated) {
                alert("אנא התחבר כדי לבצע חיפוש.");
                window.location.href = '/login';
                return;
            }

            // ולידציה: האם אושר התקנון?
            if (legalConfirm && !legalConfirm.checked) {
                if (legalError) {
                    legalError.classList.remove('hidden');
                    legalError.classList.add('flex'); // להצגה עם flex ב-Tailwind
                }
                return;
            } else if (legalError) {
                legalError.classList.add('hidden');
                legalError.classList.remove('flex');
            }

            // הצגת מצב טעינה
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.classList.add('opacity-75', 'cursor-not-allowed');
            }
            if (spinner) spinner.classList.remove('hidden');
            // if (buttonText) buttonText.textContent = 'מנתח נתונים...'; // אופציונלי

            // הסתרת תוצאות קודמות
            if (resultsContainer) resultsContainer.classList.add('hidden');

            // איסוף הנתונים
            const formData = new FormData(form);
            const searchData = Object.fromEntries(formData.entries());

            try {
                console.log("Sending search request:", searchData); // לוג לבדיקה
                const response = await fetch('/search', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(searchData)
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || 'שגיאה בביצוע החיפוש');
                }

                const data = await response.json();
                console.log("Search results received:", data); // לוג לבדיקה

                // הצגת התוצאות באמצעות הפונקציה החדשה (אם קיימת) או הישנה
                if (typeof window.displayResultsOverride === 'function') {
                    window.displayResultsOverride(data);
                } else {
                    // fallback לפונקציה פשוטה אם החדשה לא נטענה
                    alert("תוצאות התקבלו, אך פונקציית התצוגה החדשה חסרה.\n" + data.response.substring(0, 100) + "...");
                }

            } catch (error) {
                console.error('Error:', error);
                alert('אירעה שגיאה: ' + error.message);
            } finally {
                // איפוס מצב טעינה
                if (submitButton) {
                    submitButton.disabled = false;
                    submitButton.classList.remove('opacity-75', 'cursor-not-allowed');
                }
                if (spinner) spinner.classList.add('hidden');
                // if (buttonText) buttonText.textContent = '🚀 הפעל מנוע ניתוח AI';
            }
        });
    }
});

// === 3. פונקציות עזר גלובליות (טאבים וכו') ===

// נדרש ש-marked.js יהיה טעון בדף כדי לפרסר Markdown
// אם הוא לא קיים, נוסיף פונקציית דמה פשוטה
if (typeof marked === 'undefined') {
    window.marked = { parse: (text) => text.replace(/\n/g, '<br>') };
}
