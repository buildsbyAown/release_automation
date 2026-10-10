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
    </article>`;
}

function renderProducts(products) {
  document.getElementById("product-grid").innerHTML = products.map(productCard).join("");
}

const THEME_KEY = "fresh-market-theme";

function applyTheme(dark) {
  document.body.classList.toggle("dark", dark);
  document.getElementById("theme-toggle").textContent = dark ? "Light mode" : "Dark mode";
}

function preferredDarkTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved) return saved === "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function setupThemeToggle() {
  applyTheme(preferredDarkTheme());
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const dark = !document.body.classList.contains("dark");
    applyTheme(dark);
    localStorage.setItem(THEME_KEY, dark ? "dark" : "light");
  });
}

document.addEventListener("DOMContentLoaded", () => {
  renderProducts(PRODUCTS);
  setupThemeToggle();
});
