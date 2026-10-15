#include "fixture.h"

namespace
{
	struct unit final : fixture::shape
	{
		double area() const noexcept override
		{
			return 1.0;
		}
	};
}

int main()
{
	const unit one{};
	const fixture::square stack{ 2.0 };
	fixture::square* heap = new fixture::square{ 3.0 };
	const fixture::square scaled = *heap * 2.0;
	const int doubled = fixture::doubler{}(static_cast<bool>(scaled) ? 1 : 0);
	const int result = fixture::add(static_cast<int>(stack.area()), fixture::twice(versioned_answer())) + doubled;
	const int tripled = fixture::thrice(result) + fixture::dispatched() + fixture::shared;
	delete heap;
	return tripled + static_cast<int>(one.area());
}
