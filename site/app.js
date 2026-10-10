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
  const grid = document.getElementById("product-grid");
  grid.innerHTML = products.length
    ? products.map(productCard).join("")
    : '<p class="no-results">No products match your search.</p>';
}

function filterProducts() {
  const query = document.getElementById("search").value.trim().toLowerCase();
  const category = document.getElementById("category").value;
  renderProducts(PRODUCTS.filter((product) =>
    product.name.toLowerCase().includes(query) &&
    (category === "all" || product.category === category)
  ));
}

document.addEventListener("DOMContentLoaded", () => {
  renderProducts(PRODUCTS);
  document.getElementById("search").addEventListener("input", filterProducts);
  document.getElementById("category").addEventListener("change", filterProducts);
});
