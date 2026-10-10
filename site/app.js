const PRODUCTS = [
  { id: 1, name: "Apples", price: 3.5, category: "fruit" },
  { id: 2, name: "Bananas", price: 1.2, category: "fruit" },
  { id: 3, name: "Carrots", price: 2.0, category: "vegetable" },
  { id: 4, name: "Spinach", price: 2.8, category: "vegetable" },
  { id: 5, name: "Sourdough", price: 5.0, category: "bakery" },
  { id: 6, name: "Croissant", price: 2.5, category: "bakery" },
];

function productCard(product) {
  return `
    <article class="product-card">
      <h3>${product.name}</h3>
      <p class="price">$${product.price.toFixed(2)}</p>
      <button class="add-to-cart" type="button" data-id="${product.id}">Add to cart</button>
    </article>`;
}

/* Render products, showing a message when the list is empty (Ticket 53) */
function renderProducts(products) {
  const grid = document.getElementById("product-grid");
  grid.innerHTML = products.length
    ? products.map(productCard).join("")
    : '<p class="no-results">No products match your search.</p>';
}

/* Search + optional category filter (Ticket 53 S1‑S3) */
function filterProducts() {
  const query = document.getElementById("search").value.trim().toLowerCase();

  // Category filter is optional – if the element does not exist we treat it as "all"
  const categorySelect = document.getElementById("category");
  const category = categorySelect ? categorySelect.value : "all";

  renderProducts(
    PRODUCTS.filter(
      (product) =>
        product.name.toLowerCase().includes(query) &&
        (category === "all" || product.category === category)
    )
  );
}

/* Dark‑mode handling from Ticket 51 (enhanced by Ticket 51 D3/D4) */
const THEME_KEY = "fresh-market-theme";

function applyTheme(dark) {
  document.body.classList.toggle("dark", dark);
  document.getElementById("theme-toggle").textContent = dark ? "Light mode" : "Dark mode";
}

/* New helper from Ticket 51 D4: respect system colour scheme on first visit */
function preferredDarkTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved) return saved === "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function setupThemeToggle() {
  // Apply saved preference or fall back to system preference
  applyTheme(preferredDarkTheme());
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const dark = !document.body.classList.contains("dark");
    applyTheme(dark);
    localStorage.setItem(THEME_KEY, dark ? "dark" : "light");
  });
}

/* Cart functionality from Ticket 52 */
const cart = [];

function updateCartCount() {
  document.getElementById("cart-count").textContent = `Cart: ${cart.length}`;
}

function renderCart() {
  document.getElementById("cart-items").innerHTML = cart
    .map((item, index) => `
      <li>
        ${item.name} - $${item.price.toFixed(2)}
        <button class="remove-item" type="button" data-index="${index}">Remove</button>
      </li>`)
    .join("");
  const total = cart.reduce((sum, item) => sum + item.price, 0);
  document.getElementById("cart-total").textContent = total.toFixed(2);
  updateCartCount();
}

function setupCart() {
  document.getElementById("product-grid").addEventListener("click", (event) => {
    const button = event.target.closest(".add-to-cart");
    if (!button) return;
    const product = PRODUCTS.find((item) => item.id === Number(button.dataset.id));
    cart.push(product);
    renderCart();
  });
  document.getElementById("cart-items").addEventListener("click", (event) => {
    const button = event.target.closest(".remove-item");
    if (!button) return;
    cart.splice(Number(button.dataset.index), 1);
    renderCart();
  });
}

/* Initialise everything */
document.addEventListener("DOMContentLoaded", () => {
  renderProducts(PRODUCTS);
  setupThemeToggle();   // Ticket 51
  setupCart();          // Ticket 52
  document.getElementById("search").addEventListener("input", filterProducts); // Ticket 53 S1
  const categoryEl = document.getElementById("category");
  if (categoryEl) {
    categoryEl.addEventListener("change", filterProducts); // Ticket 53 S3
  }

  // Clear‑filters button (Ticket 53 S4)
  const clearBtn = document.getElementById("clear-filters");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      document.getElementById("search").value = "";
      if (categoryEl) categoryEl.value = "all";
      filterProducts();
    });
  }
});
