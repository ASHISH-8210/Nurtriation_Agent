/**
 * NutriMind — Interactive AI Nutritionist Frontend Client
 */

let currentProfile = null;
let currentMealPlan = null;

document.addEventListener('DOMContentLoaded', () => {
  initApp();
});

async function initApp() {
  await loadUserProfile();
  setupEventListeners();
  loadDefaultMealPlan();
}

// ---------------------------------------------------------------------------
// Profile Management
// ---------------------------------------------------------------------------
async function loadUserProfile() {
  try {
    const res = await fetch('/api/profile');
    if (res.ok) {
      currentProfile = await res.json();
      renderProfilePills();
      populateProfileModal();
    }
  } catch (err) {
    console.warn('Could not load profile:', err);
  }
}

function renderProfilePills() {
  const container = document.getElementById('profilePills');
  if (!container || !currentProfile) return;

  const diet = currentProfile.dietary_pattern || 'Omnivore';
  const conditions = (currentProfile.medical_conditions || []).map(c => c.replace('_', ' '));
  const allergies = (currentProfile.allergies || []).map(a => a.replace('_', ' '));
  const calories = currentProfile.calorie_target || 1600;

  let pillsHtml = `
    <span class="profile-pill highlight">🥗 ${diet.toUpperCase()}</span>
    <span class="profile-pill">🎯 ${calories} kcal/day</span>
  `;

  conditions.forEach(c => {
    pillsHtml += `<span class="profile-pill">🩺 ${c}</span>`;
  });

  allergies.forEach(a => {
    pillsHtml += `<span class="profile-pill danger">🚫 No ${a}</span>`;
  });

  container.innerHTML = pillsHtml;

  // Update profile button text
  const btnText = document.getElementById('userProfileSummary');
  if (btnText) {
    btnText.textContent = `${currentProfile.demographics?.name || 'My Profile'} (${diet})`;
  }
}

function populateProfileModal() {
  if (!currentProfile) return;
  document.getElementById('inputName').value = currentProfile.demographics?.name || 'Alex';
  document.getElementById('inputDiet').value = currentProfile.dietary_pattern || 'vegetarian';
  document.getElementById('inputCalories').value = currentProfile.calorie_target || 1600;
  document.getElementById('inputConditions').value = (currentProfile.medical_conditions || []).join(', ');
  document.getElementById('inputAllergies').value = (currentProfile.allergies || []).join(', ');
}

// ---------------------------------------------------------------------------
// Event Listeners
// ---------------------------------------------------------------------------
function setupEventListeners() {
  const chatInput = document.getElementById('chatInput');
  const btnSend = document.getElementById('btnSend');
  const btnVoice = document.getElementById('btnVoice');
  const btnUpload = document.getElementById('btnUpload');
  const imageUploadInput = document.getElementById('imageUploadInput');

  btnSend.addEventListener('click', () => {
    const text = chatInput.value.trim();
    if (text) {
      sendChatMessage(text);
      chatInput.value = '';
    }
  });

  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      btnSend.click();
    }
  });

  // Suggestion chips
  document.querySelectorAll('.suggestion-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const prompt = chip.getAttribute('data-prompt');
      if (prompt) {
        sendChatMessage(prompt);
      }
    });
  });

  // Voice simulation
  btnVoice.addEventListener('click', () => {
    btnVoice.classList.toggle('active');
    if (btnVoice.classList.contains('active')) {
      chatInput.placeholder = '🎙️ Listening via Watson STT... Speak now...';
      setTimeout(() => {
        chatInput.value = 'I had brown rice with lentils and spinach for lunch, how many calories?';
        chatInput.placeholder = 'Ask NutriMind about meal plans, swaps, ingredients, or health goals...';
        btnVoice.classList.remove('active');
      }, 2500);
    }
  });

  // Photo Upload trigger
  btnUpload.addEventListener('click', () => {
    imageUploadInput.click();
  });

  imageUploadInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      handleImageAnalysis(e.target.files[0]);
    }
  });

  // Modal open/close
  const btnOpenProfile = document.getElementById('btnOpenProfile');
  const modalProfile = document.getElementById('modalProfile');
  const btnCloseModal = document.getElementById('btnCloseModal');
  const formProfile = document.getElementById('formProfile');

  btnOpenProfile.addEventListener('click', () => modalProfile.classList.add('open'));
  btnCloseModal.addEventListener('click', () => modalProfile.classList.remove('open'));
  modalProfile.addEventListener('click', (e) => {
    if (e.target === modalProfile) modalProfile.classList.remove('open');
  });

  formProfile.addEventListener('submit', async (e) => {
    e.preventDefault();
    const updatedDelta = {
      demographics: {
        ...currentProfile.demographics,
        name: document.getElementById('inputName').value.trim()
      },
      dietary_pattern: document.getElementById('inputDiet').value,
      calorie_target: parseInt(document.getElementById('inputCalories').value) || 1600,
      medical_conditions: document.getElementById('inputConditions').value.split(',').map(s => s.trim().toLowerCase()).filter(Boolean),
      allergies: document.getElementById('inputAllergies').value.split(',').map(s => s.trim().toLowerCase()).filter(Boolean)
    };

    try {
      const res = await fetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedDelta)
      });
      if (res.ok) {
        const data = await res.json();
        currentProfile = data.profile;
        renderProfilePills();
        modalProfile.classList.remove('open');
        appendMessage('assistant', `✅ **Profile updated successfully!** I have synchronized your **${currentProfile.dietary_pattern}** diet, allergen guards, and **${currentProfile.calorie_target} kcal** target.`);
      }
    } catch (err) {
      alert('Failed to save profile: ' + err);
    }
  });

  // Quick USDA search
  const btnSearch = document.getElementById('btnSearch');
  const searchInput = document.getElementById('searchNutritionInput');
  btnSearch.addEventListener('click', () => {
    const q = searchInput.value.trim();
    if (q) queryUSDANutrition(q);
  });
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') btnSearch.click();
  });
}

// ---------------------------------------------------------------------------
// Chat Communication
// ---------------------------------------------------------------------------
async function sendChatMessage(message) {
  appendMessage('user', message);
  showTypingIndicator();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: message })
    });

    removeTypingIndicator();

    if (res.ok) {
      const data = await res.json();
      appendMessage('assistant', data.response, data);

      // If a meal plan was generated, update the right panel
      if (data.meal_plan) {
        currentMealPlan = data.meal_plan;
        renderMealPlanSidebar(currentMealPlan);
      }
    } else {
      appendMessage('assistant', '⚠️ Sorry, could not process that request. Please try again.');
    }
  } catch (err) {
    removeTypingIndicator();
    appendMessage('assistant', '⚠️ Connection error with NutriMind backend: ' + err.message);
  }
}

function appendMessage(role, content, meta = null) {
  const container = document.getElementById('chatHistory');
  const row = document.createElement('div');
  row.className = `message-row ${role}`;

  const avatar = document.createElement('div');
  avatar.className = 'message-avatar';
  avatar.innerHTML = role === 'assistant' ? '🥗' : '👤';

  const bubble = document.createElement('div');
  bubble.className = 'message-bubble';

  // Tool badge if available
  if (meta && meta.detected_tool) {
    const toolBadge = document.createElement('div');
    toolBadge.className = 'tool-tag';
    toolBadge.innerHTML = `⚡ Executed: ${meta.detected_tool}`;
    bubble.appendChild(toolBadge);
  }

  const textDiv = document.createElement('div');
  textDiv.innerHTML = formatMarkdown(content);
  bubble.appendChild(textDiv);

  row.appendChild(avatar);
  row.appendChild(bubble);
  container.appendChild(row);

  container.scrollTop = container.scrollHeight;
}

function showTypingIndicator() {
  const container = document.getElementById('chatHistory');
  const typingRow = document.createElement('div');
  typingRow.id = 'typingIndicator';
  typingRow.className = 'message-row assistant';
  typingRow.innerHTML = `
    <div class="message-avatar">🥗</div>
    <div class="message-bubble typing-bubble">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>
  `;
  container.appendChild(typingRow);
  container.scrollTop = container.scrollHeight;
}

function removeTypingIndicator() {
  const ind = document.getElementById('typingIndicator');
  if (ind) ind.remove();
}

// ---------------------------------------------------------------------------
// Markdown Formatter (Lightweight)
// ---------------------------------------------------------------------------
function formatMarkdown(text) {
  if (!text) return '';
  let formatted = text
    .replace(/^#### (.*$)/gim, '<h4>$1</h4>')
    .replace(/^### (.*$)/gim, '<h3>$1</h3>')
    .replace(/^## (.*$)/gim, '<h2>$1</h2>')
    .replace(/^# (.*$)/gim, '<h1>$1</h1>')
    .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/gim, '<em>$1</em>')
    .replace(/`([^`]+)`/gim, '<code>$1</code>')
    .replace(/^\s*-\s+(.*$)/gim, '<li>$1</li>')
    .replace(/\n\n/gim, '<p></p>')
    .replace(/\n/gim, '<br />');

  return formatted;
}

// ---------------------------------------------------------------------------
// Image Analysis
// ---------------------------------------------------------------------------
async function handleImageAnalysis(file) {
  appendMessage('user', `📸 *[Uploaded Image: ${file.name}]*`);
  showTypingIndicator();

  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const res = await fetch('/api/analyze-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: reader.result, hint: file.name })
      });
      removeTypingIndicator();
      if (res.ok) {
        const data = await res.json();
        const items = data.foods.map(f => `• **${f.name}**: ~${f.quantity_estimate}${f.unit} (${f.confidence} confidence)`).join('<br>');
        const analysis = `
          ### 📸 Granite Vision Food Analysis
          ${items}
          <br><br>
          **Estimated Nutrition**:
          • **Calories**: \`${data.total_nutrition_estimate.calories_kcal} kcal\`
          • **Protein**: \`${data.total_nutrition_estimate.protein_g} g\`
          • **Carbs**: \`${data.total_nutrition_estimate.carbs_g} g\`
          • **Fiber**: \`${data.total_nutrition_estimate.fiber_g} g\`
          <br><br>
          💡 *${data.dietary_analysis}*
        `;
        appendMessage('assistant', analysis, { detected_tool: 'analyze_food_image' });
      }
    } catch (err) {
      removeTypingIndicator();
      appendMessage('assistant', '⚠️ Failed to analyze image: ' + err.message);
    }
  };
  reader.readAsDataURL(file);
}

// ---------------------------------------------------------------------------
// Quick USDA Nutrition Search
// ---------------------------------------------------------------------------
async function queryUSDANutrition(food) {
  const resDiv = document.getElementById('searchResults');
  resDiv.innerHTML = '<div style="color:var(--text-muted);">Fetching USDA data...</div>';

  try {
    const res = await fetch(`/api/nutrition?q=${encodeURIComponent(food)}&qty=100`);
    if (res.ok) {
      const data = await res.json();
      const p = data.for_quantity;
      resDiv.innerHTML = `
        <div style="background:var(--bg-surface-elevated); padding:10px; border-radius:8px; border:1px solid var(--border-subtle)">
          <div style="font-weight:700; color:var(--accent-primary-hover);">${data.food_name}</div>
          <div style="font-size:0.72rem; color:var(--text-muted); margin-bottom:6px;">Per 100g serving</div>
          <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
            <span>Calories:</span> <strong>${p.calories_kcal || 0} kcal</strong>
          </div>
          <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
            <span>Protein:</span> <strong>${p.protein_g || 0} g</strong>
          </div>
          <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
            <span>Carbohydrates:</span> <strong>${p.carbs_g || 0} g</strong>
          </div>
          <div style="display:flex; justify-content:space-between;">
            <span>Dietary Fiber:</span> <strong>${p.fiber_g || 0} g</strong>
          </div>
        </div>
      `;
    } else {
      resDiv.innerHTML = '<div style="color:var(--alert-danger-text);">Food not found in USDA database.</div>';
    }
  } catch (err) {
    resDiv.innerHTML = '<div style="color:var(--alert-danger-text);">Search error: ' + err.message + '</div>';
  }
}

// ---------------------------------------------------------------------------
// Meal Plan Rendering in Right Panel
// ---------------------------------------------------------------------------
async function loadDefaultMealPlan() {
  try {
    const res = await fetch('/api/meal-plan');
    if (res.ok) {
      currentMealPlan = await res.json();
      renderMealPlanSidebar(currentMealPlan);
    }
  } catch (e) {
    console.warn('Could not fetch default meal plan:', e);
  }
}

function renderMealPlanSidebar(plan) {
  if (!plan || !plan.days || plan.days.length === 0) return;
  const day = plan.days[0];
  const target = plan.target_nutrition || { calories_kcal: 1600, protein_g: 90, carbs_g: 160, fat_g: 50 };

  // Update Macro grid
  document.getElementById('calVal').textContent = `${day.total_nutrition.calories_kcal}`;
  document.getElementById('calFill').style.width = `${Math.min(100, Math.round((day.total_nutrition.calories_kcal / target.calories_kcal) * 100))}%`;

  document.getElementById('proteinVal').textContent = `${day.total_nutrition.protein_g}g`;
  document.getElementById('proteinFill').style.width = `${Math.min(100, Math.round((day.total_nutrition.protein_g / target.protein_g) * 100))}%`;

  document.getElementById('carbsVal').textContent = `${day.total_nutrition.carbs_g}g`;
  document.getElementById('carbsFill').style.width = `${Math.min(100, Math.round((day.total_nutrition.carbs_g / target.carbs_g) * 100))}%`;

  document.getElementById('fatVal').textContent = `${day.total_nutrition.fat_g}g`;
  document.getElementById('fatFill').style.width = `${Math.min(100, Math.round((day.total_nutrition.fat_g / target.fat_g) * 100))}%`;

  // Render Meal items
  const mealContainer = document.getElementById('mealItemsList');
  let mealsHtml = '';
  day.meals.forEach(meal => {
    const foodsList = meal.foods.map(f => f.name).join(', ');
    mealsHtml += `
      <div class="meal-item-card" onclick="sendChatMessage('Tell me more about ${meal.meal_type} and why it works for my health goals')">
        <div class="meal-item-header">
          <span>${meal.meal_type}</span>
          <span style="color:var(--badge-text)">${meal.meal_nutrition.calories_kcal} kcal</span>
        </div>
        <div class="meal-item-summary">${foodsList}</div>
      </div>
    `;
  });
  mealContainer.innerHTML = mealsHtml;
}
