document.addEventListener('DOMContentLoaded', () => {
    // אלמנטים מה-DOM
    const form = document.getElementById('car-form');
    const makeSelect = document.getElementById('make');
    const modelSelect = document.getElementById('model');
    const yearSelect = document.getElementById('year');
    const submitButton = document.getElementById('submit-button');
    const spinner = submitButton ? submitButton.querySelector('.spinner') : null;
    const resultsContainer = document.getElementById('results-container');
    const legalConfirm = document.getElementById('legal-confirm');
    const legalError = document.getElementById('legal-error');

    // בדיקה ראשונית של נתונים
    console.log("Initial carModelsData:", carModelsData);

    // === 1. לוגיקת בחירת רכב (Dropdowns תלויים) ===
    if (makeSelect && modelSelect && yearSelect) {
        // בעת בחירת יצרן
        makeSelect.addEventListener('change', () => {
            const selectedMake = makeSelect.value;
            console.log("Selected make:", selectedMake);

            // איפוס שדות תלויים
            modelSelect.innerHTML = '<option value="">בחר דגם...</option>';
            yearSelect.innerHTML = '<option value="">בחר יצרן תחילה...</option>';
            modelSelect.disabled = true;
            yearSelect.disabled = true;

            if (selectedMake && carModelsData && carModelsData[selectedMake]) {
                const modelsData = carModelsData[selectedMake];
                let models = [];

                // בדיקה אם המידע הוא מערך (רשימה) או אובייקט (מילון)
                if (Array.isArray(modelsData)) {
                     // אם זה מערך של מחרוזות (שמות דגמים בלבד, ללא שנתונים)
                    models = modelsData.sort();
                } else if (typeof modelsData === 'object' && modelsData !== null) {
                    // אם זה אובייקט שהמפתחות שלו הם שמות הדגמים
                    models = Object.keys(modelsData).sort();
                }

                console.log("Available models for", selectedMake, ":", models);

                if (models.length > 0) {
                    models.forEach(model => {
                        const option = document.createElement('option');
                        option.value = model;
                        option.textContent = model;
                        modelSelect.appendChild(option);
                    });
                    modelSelect.disabled = false;
                } else {
                    console.warn("No models found for make:", selectedMake);
                }
            }
        });

        // בעת בחירת דגם
        modelSelect.addEventListener('change', () => {
            const selectedMake = makeSelect.value;
            const selectedModel = modelSelect.value;
            console.log("Selected model:", selectedModel);

            yearSelect.innerHTML = '<option value="">בחר שנתון...</option>';
            yearSelect.disabled = true;

            if (selectedMake && selectedModel && carModelsData[selectedMake]) {
                let years = [];
                const modelsData = carModelsData[selectedMake];

                // ניסיון לחלץ שנתונים בהתאם למבנה הנתונים
                if (Array.isArray(modelsData)) {
                     // אם המידע הוא רק רשימת דגמים, אין לנו שנתונים.
                     // נצטרך להציג טווח שנים גנרי או לבקש מהמשתמש להזין ידנית.
                     // כפתרון זמני, נציג רשימת שנים גנרית (למשל 2000-2024)
                     console.warn("No specific years data found for model. Using generic range.");
                     for (let y = 2025; y >= 2000; y--) years.push(y);
                } else if (typeof modelsData === 'object' && modelsData !== null && modelsData[selectedModel]) {
                     // אם יש מידע ספציפי לשנתונים עבור הדגם
                     years = modelsData[selectedModel];
                     // וודא שזה מערך
                     if (!Array.isArray(years)) {
                         console.warn("Years data is not an array:", years);
                         years = []; // או טיפול אחר
                     }
                }

                if (years.length > 0) {
                    // מיון שנתונים יורד (מהחדש לישן)
                    years.sort((a, b) => b - a);
                    years.forEach(year => {
                        const option = document.createElement('option');
                        option.value = year;
                        option.textContent = year;
                        yearSelect.appendChild(option);
                    });
                    yearSelect.disabled = false;
                } else {
                     // אם לא נמצאו שנתונים, אפשר לאפשר הזנה ידנית או להציג טווח ברירת מחדל
                     console.warn("Could not find years for", selectedModel);
                     // אופציה: להוסיף שנים גנריות כגיבוי
                     for (let y = 2025; y >= 2000; y--) {
                         const option = document.createElement('option');
                         option.value = y;
                         option.textContent = y;
                         yearSelect.appendChild(option);
                     }
                     yearSelect.disabled = false;
                }
            }
        });
    }

    // === 2. שליחת הטופס וטיפול בתוצאות ===
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
            const searchData = Object.fromEntries(formData.entries());

            try {
                console.log("Sending search:", searchData);
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
                console.log("Results received:", data);

                if (typeof window.displayResultsOverride === 'function') {
                    window.displayResultsOverride(data);
                } else {
                    alert("התקבלו תוצאות, אך רכיב התצוגה חסר. בדוק את הקונסול.");
                    console.log("Raw results:", data.response);
                }

            } catch (error) {
                console.error('Search error:', error);
                alert('אירעה שגיאה: ' + error.message);
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
