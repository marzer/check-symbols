#pragma once

namespace fixture
{
	class shape
	{
	  public:
		virtual ~shape() noexcept;
		virtual double area() const noexcept = 0;
	};

	class square final : public shape
	{
		double side_ = {};

	  public:
		explicit square(double side) noexcept;
		double area() const noexcept override;
		explicit operator bool() const noexcept;

		static void* operator new(decltype(sizeof(0)) size);
		static void operator delete(void* ptr) noexcept;
	};

	square operator*(const square& lhs, double rhs) noexcept;

	struct doubler
	{
		int operator()(int value) const noexcept;
	};

	int add(int lhs, int rhs) noexcept;
	double add(double lhs, double rhs) noexcept;

	template <typename T>
	T twice(T value) noexcept;

	template <>
	int twice<int>(int value) noexcept;

	template <typename T>
	T thrice(T value) noexcept;

	int not_imported() noexcept;

	int dispatched() noexcept;

	extern int counter;
	extern int seed;
	extern int fallback;
	extern const int table[4];

	inline int shared = 5;
}

extern "C" int versioned_answer() noexcept;
