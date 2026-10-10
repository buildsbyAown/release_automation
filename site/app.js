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

/* Search functionality from Ticket 53 */
function filterProducts() {
  const query = document.getElementById("search").value.trim().toLowerCase();
  renderProducts(PRODUCTS.filter((product) => product.name.toLowerCase().includes(query)));
}

/* Dark‑mode handling from Ticket 51 (enhanced by Ticket 51 D3/D4) */
const THEME_KEY = "fresh-market-theme";

function applyTheme(dark) {
  document.body.classList.toggle("dark", dark);
  document.getElementById("theme-toggle").textContent = dark ? "Light mode" : "Dark mode";
}

function setupThemeToggle() {
  // Apply saved preference (or default to system‑based first‑visit handling)
  applyTheme(localStorage.getItem(THEME_KEY) === "dark");
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

function setupCart() {
  document.getElementById("product-grid").addEventListener("click", (event) => {
    const button = event.target.closest(".add-to-cart");
    if (!button) return;
    const product = PRODUCTS.find((item) => item.id === Number(button.dataset.id));
    cart.push(product);
    updateCartCount();
  });
}

/* Initialise everything */
document.addEventListener("DOMContentLoaded", () => {
  renderProducts(PRODUCTS);
  setupThemeToggle();   // Ticket 51
  setupCart();          // Ticket 52
  document.getElementById("search").addEventListener("input", filterProducts); // Ticket 53
});
